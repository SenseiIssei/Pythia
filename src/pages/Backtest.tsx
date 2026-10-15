import { useMemo, useState } from "react";
import { FlaskConical, Play } from "lucide-react";
import { useStore } from "../store";
import { AreaChart, Button, Card, Field, List, Notice, Page, changeTone, inputCls, money, signedPct } from "../design";
import { CostLines, KeyStats, More, Nothing, Row, Section, pct, plural, share } from "../pagekit";
import { finalValue } from "../pagekit/riskLab";
import { backtest, type BacktestResult } from "../engine/backtest";
import { costVenueFor, modelFor } from "../engine/costs";
import type { StrategyConfig } from "../types";

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

  const last = result ? finalValue(result.equityCurve) : null;

  return (
    <Page title="Backtest" subtitle="Replay a strategy over made-up price history, with the same signal code as the live engine, to see how it would have done.">
      <Section title="Settings" hint="Pick a strategy and how the made-up market should behave, then run it.">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Strategy" className="sm:col-span-2" hint={`${plural(testable.length, "strategy", "strategies")} can be tested here. Pairs and Prob-Edge need several markets or a model, so they are left out.`}>
            <select value={strat?.id ?? ""} onChange={(e) => setStratId(e.target.value)} className={inputCls}>
              {testable.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
          <NumField label="Bars" hint="How many candles to replay" value={bars} onChange={setBars} step={100} min={200} max={6000} />
          <NumField label="Seed" hint="The same seed gives the same history" value={seed} onChange={setSeed} step={1} min={1} max={999999} />
          <NumField label="Volatility" hint="Typical move per candle, 0.015 is 1.5 %" value={vol} onChange={setVol} step={0.001} min={0.002} max={0.06} />
          <NumField label="Drift per bar" hint="Built-in trend per candle, up or down" value={drift} onChange={setDrift} step={0.0001} min={-0.002} max={0.002} />
        </div>
        <div className="mt-5">
          <Button variant="primary" icon={Play} onClick={run} disabled={!strat}>
            Run backtest
          </Button>
        </div>
      </Section>

      {result && !result.ok && (
        <Notice tone="warning" title="This strategy cannot be backtested here">
          {result.message}
        </Notice>
      )}

      {!result && (
        <Card>
          <Nothing icon={FlaskConical} title="No test run yet">
            Pick a strategy and press Run backtest. The results appear here.
          </Nothing>
        </Card>
      )}

      {result && result.ok && (
        <>
          <KeyStats
            items={[
              { label: "Net Return", value: signedPct(result.totalReturnPct, 1), tone: changeTone(result.totalReturnPct), sub: "What the test account kept after costs" },
              { label: "Max Drawdown", value: pct(result.maxDrawdownPct, 1), sub: "Worst fall from a high" },
              { label: "Win Rate", value: share(result.winRate), sub: plural(result.trades, "trade") },
            ]}
          />

          <Section
            title="Gross, costs, net"
            hint="What the trades made before costs, what trading cost, and what was left."
            help="Gross is what the same trades would have made at the quoted price with no fees, spread or impact."
          >
            <CostLines pnl={result.pnl} />
            <p className="mt-2 break-words text-[13px] leading-relaxed text-muted">
              Cost model: <span className={result.pnl.costHeavy ? "font-semibold text-warn" : "text-ink"}>{costLabel(strat)}</span>. Costs come from config/costs.json
              for this venue and market.
            </p>
          </Section>

          <Section title="Test account value" hint="The account's value over the made-up history, starting from $10,000.">
            <AreaChart
              data={result.equityCurve}
              height={200}
              tone={changeTone(result.totalReturnPct)}
              label="Backtest account value"
              renderTip={(i) => money(result.equityCurve[i], 0)}
            />
            <List className="mt-3">
              <Row label="Final value" value={last == null ? "n/a" : money(last, 0)} />
              <Row
                label="Profit factor"
                value={result.profitFactor.toFixed(2)}
                tone={result.profitFactor >= 1 ? "up" : "down"}
                valueSub={result.profitFactor >= 1 ? "winners outweigh losers" : "losers outweigh winners"}
              />
              <Row label="Sharpe" value={result.sharpe.toFixed(2)} tone={result.sharpe >= 1 ? "up" : result.sharpe < 0 ? "down" : "plain"} />
            </List>
            <More title="Test details">
              <p className="tabular text-[13px] text-muted">
                {plural(result.bars, "bar")} · seed {seed}
              </p>
            </More>
          </Section>

          <Notice tone="info">
            Made-up prices: a good backtest here is necessary, not sufficient. Real markets have bigger surprises, slippage and fewer buyers and sellers. Prove a
            strategy in practice too.
          </Notice>
        </>
      )}
    </Page>
  );
}

/** "Kraken · 40 bps fee + 2 bps spread per side" for the strategy's first market. */
function costLabel(s?: StrategyConfig): string {
  if (!s) return "";
  const venue = costVenueFor(s.venueClass);
  const symbol = (s.universe[0] ?? "").split(":")[1] ?? "";
  const m = modelFor(venue, symbol);
  return `${venue} · ${m.takerBps} bps fee + ${m.halfSpreadBps} bps spread per side`;
}

function NumField({ label, hint, value, onChange, step, min, max }: { label: string; hint?: string; value: number; onChange: (v: number) => void; step: number; min: number; max: number }) {
  return (
    <Field label={label} hint={hint}>
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
