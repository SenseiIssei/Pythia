import { Fragment, useMemo, useState } from "react";
import { Sparkles, Play, Trophy } from "lucide-react";
import { useStore } from "../store";
import { Button, Card, PageHeader, Badge, StatCard } from "../components/ui";
import { autoGrid, monteCarlo, sweep, type SweepPoint, type MonteCarlo } from "../engine/optimize";
import { Dice5, TrendingUp, ShieldCheck, Activity } from "lucide-react";

export function Optimizer() {
  const { strategies } = useStore();
  const testable = strategies.filter((s) => !["pairs", "prob-edge", "manual", "arb"].includes(s.kind));
  const [stratId, setStratId] = useState(testable[0]?.id ?? "");
  const [seeds, setSeeds] = useState(12);
  const [bars, setBars] = useState(700);
  const [vol, setVol] = useState(0.02);
  const [running, setRunning] = useState(false);
  const [points, setPoints] = useState<SweepPoint[] | null>(null);
  const [mc, setMc] = useState<MonteCarlo | null>(null);

  const strat = useMemo(() => strategies.find((s) => s.id === stratId), [strategies, stratId]);
  const paramKeys = useMemo(() => (strat ? Object.keys(autoGrid(strat)) : []), [strat]);

  function run() {
    if (!strat) return;
    setRunning(true);
    setPoints(null);
    setMc(null);
    // yield so the spinner paints before the heavy synchronous sweep
    setTimeout(() => {
      const grid = autoGrid(strat);
      const pts = sweep(strat, grid, seeds, { bars, vol });
      const best = pts[0];
      const bestCfg = best
        ? { ...strat, params: strat.params.map((p) => (p.key in best.params ? { ...p, value: best.params[p.key] } : p)) }
        : strat;
      const dist = monteCarlo(bestCfg, seeds, { bars, vol });
      setPoints(pts);
      setMc(dist);
      setRunning(false);
    }, 30);
  }

  return (
    <div className="animate-fade-in">
      <PageHeader title="Optimizer" subtitle="Sweep parameters across many random histories — robust, not lucky" />

      <Card className="mb-4">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <label className="text-xs text-cyber-text-dim">
            Strategy
            <select
              value={stratId}
              onChange={(e) => setStratId(e.target.value)}
              className="mt-1 w-full rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm text-cyber-text focus:border-accent focus:outline-none"
            >
              {testable.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </label>
          <NumField label="Seeds / combo" value={seeds} onChange={setSeeds} step={1} min={4} max={40} />
          <NumField label="Bars" value={bars} onChange={setBars} step={100} min={300} max={2000} />
          <NumField label="Volatility" value={vol} onChange={setVol} step={0.001} min={0.005} max={0.05} />
        </div>
        <div className="mt-3 flex items-center gap-3">
          <Button tone="purple" icon={Play} onClick={run} disabled={!strat || running}>
            {running ? "Optimizing…" : "Run optimization"}
          </Button>
          <span className="text-xs text-cyber-text-faint">
            <Sparkles size={11} className="mr-1 inline" />
            sweeps {paramKeys.join(", ") || "params"} · each combo Monte-Carlo'd across {seeds} seeds
          </span>
        </div>
      </Card>

      {mc && (
        <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="Median Return" value={`${mc.medianReturn >= 0 ? "+" : ""}${mc.medianReturn.toFixed(1)}%`} icon={TrendingUp} tone={mc.medianReturn >= 0 ? "green" : "red"} sub="best combo, across seeds" />
          <StatCard label="% Profitable" value={`${(mc.pctProfitable * 100).toFixed(0)}%`} icon={ShieldCheck} tone={mc.pctProfitable >= 0.5 ? "green" : "red"} sub={`${mc.seeds} seeds`} />
          <StatCard label="Median Sharpe" value={mc.medianSharpe.toFixed(2)} icon={Activity} tone={mc.medianSharpe >= 1 ? "green" : mc.medianSharpe >= 0 ? "cyan" : "red"} />
          <StatCard label="Worst Drawdown" value={`${mc.worstDD.toFixed(1)}%`} icon={Dice5} tone="red" sub={`worst ${mc.worstReturn.toFixed(0)}% / best +${mc.bestReturn.toFixed(0)}%`} />
        </div>
      )}

      {points && (
        <Card title="Parameter Sweep — ranked by robustness" right={<Trophy size={14} className="text-warning" />}>
          <div className="overflow-x-auto">
            <div className="grid min-w-[520px]" style={{ gridTemplateColumns: `repeat(${paramKeys.length}, auto) repeat(4, 1fr)` }}>
              {paramKeys.map((k) => (
                <Head key={k}>{k}</Head>
              ))}
              <Head right>Med. Ret</Head>
              <Head right>Med. Sharpe</Head>
              <Head right>% Prof</Head>
              <Head right>Worst DD</Head>
              {points.slice(0, 15).map((p, i) => (
                <Fragment key={i}>
                  {paramKeys.map((k) => (
                    <Cell key={k} className={i === 0 ? "text-accent" : ""}>
                      {i === 0 && k === paramKeys[0] ? <Badge tone="green">best</Badge> : null} {p.params[k]}
                    </Cell>
                  ))}
                  <Cell className={p.medianReturn >= 0 ? "text-success" : "text-danger"}>{p.medianReturn.toFixed(1)}%</Cell>
                  <Cell>{p.medianSharpe.toFixed(2)}</Cell>
                  <Cell>{(p.pctProfitable * 100).toFixed(0)}%</Cell>
                  <Cell className="text-danger">{p.worstDD.toFixed(1)}%</Cell>
                </Fragment>
              ))}
            </div>
          </div>
          <div className="mt-3 text-xs text-cyber-text-faint">
            Ranked by a robustness score (median return × consistency − drawdown penalty). A combo that only
            wins on one seed sinks to the bottom. Synthetic data — treat as a filter, not a promise.
          </div>
        </Card>
      )}
    </div>
  );
}

function Head({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <div className={`border-b border-cyber-border px-2 pb-2 text-xs uppercase text-cyber-text-faint ${right ? "text-right" : ""}`}>{children}</div>;
}
function Cell({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`border-b border-cyber-border/40 px-2 py-2 text-right font-mono text-sm ${className}`}>{children}</div>;
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
