import { Fragment, useMemo, useState } from "react";
import { Sparkles, Play, Trophy, Database, AlertTriangle } from "lucide-react";
import { useStore } from "../store";
import { Button, Card, PageHeader, Badge, StatCard } from "../components/ui";
import { autoGrid, monteCarlo, sweep, walkForward, type SweepPoint, type MonteCarlo, type WalkForward } from "../engine/optimize";
import { Dice5, TrendingUp, ShieldCheck, Activity, GitBranch } from "lucide-react";
import { researchAvailable, runSweep } from "../research";
import { costWarning } from "../components/PnlBreakdown";
import type { SweepReport, SweepRow } from "../types";

/** The two numbers that say how much of an optimizer result to believe. */
const RATIO_BAR = 0.5;
const P_BAR = 0.05;

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
  const [wf, setWf] = useState<WalkForward | null>(null);
  const [real, setReal] = useState<SweepReport | null>(null);
  const [realBusy, setRealBusy] = useState(false);
  const [realErr, setRealErr] = useState("");
  const canResearch = researchAvailable();

  // Strategies arrive with the first engine push, possibly after this page
  // mounted, so an empty pick falls back to the first testable one.
  const strat = useMemo(
    () => strategies.find((s) => s.id === stratId) ?? (stratId ? undefined : testable[0]),
    [strategies, stratId, testable]
  );
  const paramKeys = useMemo(() => (strat ? Object.keys(autoGrid(strat)) : []), [strat]);

  async function runReal() {
    if (!strat) return;
    setRealBusy(true);
    setRealErr("");
    setReal(null);
    try {
      setReal(await runSweep(strat.id));
    } catch (e) {
      setRealErr(String(e instanceof Error ? e.message : e));
    }
    setRealBusy(false);
  }

  function run() {
    if (!strat) return;
    setRunning(true);
    setPoints(null);
    setMc(null);
    setWf(null);
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

  function runWalkForward() {
    if (!strat) return;
    setRunning(true);
    setWf(null);
    setTimeout(() => {
      const grid = autoGrid(strat);
      setWf(walkForward(strat, grid, seeds, { bars, vol }));
      setRunning(false);
    }, 30);
  }

  return (
    <div className="animate-fade-in">
      <PageHeader title="Optimizer" subtitle="Every result next to the two numbers that say how much of it to believe" />

      <Card className="mb-4">
        <label className="block max-w-sm text-xs text-cyber-text-dim">
          Strategy
          <select
            value={strat?.id ?? ""}
            onChange={(e) => {
              setStratId(e.target.value);
              setReal(null);
              setPoints(null);
            }}
            className="mt-1 w-full rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm text-cyber-text focus:border-accent focus:outline-none"
          >
            {testable.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </label>
        <div className="mt-3 text-xs text-cyber-text-faint">
          <b>Deflated Sharpe</b> asks how likely a Sharpe is to be real edge given how many configurations were
          tried: the best of many tries on pure noise always looks good. <b>OOS/IS</b> compares results on data the
          ranking never saw with the data it was chosen on; below {RATIO_BAR} the parameters are mostly noise.
        </div>
      </Card>

      <Card
        className="mb-4"
        title="Real candles"
        right={<Database size={14} className="text-accent" />}
      >
        {canResearch ? (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <Button tone="purple" icon={Play} onClick={() => void runReal()} disabled={!strat || realBusy}>
                {realBusy ? "Sweeping…" : "Sweep on real candles"}
              </Button>
              <span className="text-xs text-cyber-text-faint">
                daily candles · fit on the first 60 %, hold out the last 40 % · costs from config/costs.json
              </span>
            </div>
            {realErr && <div className="mt-2 text-xs text-danger">{realErr}</div>}
            {real && <RealSweep report={real} />}
          </>
        ) : (
          <div className="text-xs text-cyber-text-faint">
            Real-candle sweeps run in the Rust core, which this browser build does not have. Open the desktop app or
            connect a backend (<span className="font-mono">VITE_PYTHIA_SERVER</span>) to get deflated Sharpe on
            real history. The synthetic sweep below is a demo of the mechanics, not evidence.
          </div>
        )}
      </Card>

      <Card className="mb-4" title="Synthetic demo">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
          <NumField label="Seeds / combo" value={seeds} onChange={setSeeds} step={1} min={4} max={40} />
          <NumField label="Bars" value={bars} onChange={setBars} step={100} min={300} max={2000} />
          <NumField label="Volatility" value={vol} onChange={setVol} step={0.001} min={0.005} max={0.05} />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button tone="cyan" icon={Play} onClick={run} disabled={!strat || running}>
            {running ? "Optimizing…" : "Run synthetic sweep"}
          </Button>
          <Button tone="cyan" icon={GitBranch} onClick={runWalkForward} disabled={!strat || running}>
            Walk-forward test
          </Button>
          <span className="text-xs text-cyber-text-faint">
            <Sparkles size={11} className="mr-1 inline" />
            sweeps {paramKeys.join(", ") || "params"} · each combo Monte-Carlo'd across {seeds} random histories,
            then re-run on {seeds} histories it never saw
          </span>
        </div>
      </Card>

      {wf && (
        <Card
          className={`mb-4 ${wf.holdsUp ? "border-success/40 glow-green" : "border-danger/40 glow-red"}`}
          title="Walk-forward validation"
          right={<Badge tone={wf.holdsUp ? "green" : "red"}>{wf.holdsUp ? "holds up out-of-sample" : "likely overfit"}</Badge>}
        >
          <div className="mb-2 text-xs text-cyber-text-dim">
            Best params <span className="font-mono text-accent">{JSON.stringify(wf.best)}</span> optimized on
            in-sample histories, then tested on <span className="text-accent">disjoint</span> out-of-sample histories.
          </div>
          <div className="grid grid-cols-2 gap-4">
            <WfCol title="In-sample (train)" mc={wf.inSample} />
            <WfCol title="Out-of-sample (test)" mc={wf.outOfSample} />
          </div>
          <div className="mt-3 text-xs text-cyber-text-faint">
            Degradation IS→OOS: <span className={wf.degradationPct > 2 ? "text-danger" : "text-success"}>{wf.degradationPct >= 0 ? "" : "+"}{(-wf.degradationPct).toFixed(1)}pp</span>.
            {wf.holdsUp
              ? " The edge survived unseen data — a real (if modest) signal by this test."
              : " The edge mostly vanished on unseen data — classic overfitting. Don't trust it."}
          </div>
        </Card>
      )}

      {mc && (
        <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="Median Return" value={`${mc.medianReturn >= 0 ? "+" : ""}${mc.medianReturn.toFixed(1)}%`} icon={TrendingUp} tone={mc.medianReturn >= 0 ? "green" : "red"} sub="best combo, across seeds" />
          <StatCard label="% Profitable" value={`${(mc.pctProfitable * 100).toFixed(0)}%`} icon={ShieldCheck} tone={mc.pctProfitable >= 0.5 ? "green" : "red"} sub={`${mc.seeds} seeds`} />
          <StatCard label="Median Sharpe" value={mc.medianSharpe.toFixed(2)} icon={Activity} tone={mc.medianSharpe >= 1 ? "green" : mc.medianSharpe >= 0 ? "cyan" : "red"} />
          <StatCard label="Worst Drawdown" value={`${mc.worstDD.toFixed(1)}%`} icon={Dice5} tone="red" sub={`worst ${mc.worstReturn.toFixed(0)}% / best +${mc.bestReturn.toFixed(0)}%`} />
        </div>
      )}

      {points && (
        <Card title="Synthetic sweep, ranked by robustness" right={<Trophy size={14} className="text-warning" />}>
          <div className="overflow-x-auto">
            <div className="grid min-w-[760px]" style={{ gridTemplateColumns: `repeat(${paramKeys.length}, auto) repeat(7, 1fr)` }}>
              {paramKeys.map((k) => (
                <Head key={k}>{k}</Head>
              ))}
              <Head right>Med. Ret</Head>
              <Head right>Med. Sharpe</Head>
              <Head right>% Prof</Head>
              <Head right>Worst DD</Head>
              <Head right>OOS Sharpe</Head>
              <Head right>OOS/IS</Head>
              <Head right>Deflated</Head>
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
                  <Cell>{p.oosMedianSharpe.toFixed(2)}</Cell>
                  <RatioCell ratio={p.oosIsRatio} />
                  <Cell className="text-cyber-text-faint">
                    <span title="Deflated Sharpe is computed by the Rust core on real candles. Synthetic random histories are not a sample it can deflate honestly.">
                      real only
                    </span>
                  </Cell>
                </Fragment>
              ))}
            </div>
          </div>
          <div className="mt-3 text-xs text-cyber-text-faint">
            Ranked by a robustness score (median return × consistency − drawdown penalty). OOS columns re-run each
            combo on random histories the ranking never saw. Synthetic data, so a filter, not a promise: the deflated
            Sharpe lives in the real-candle sweep above.
          </div>
        </Card>
      )}
    </div>
  );
}

/** The Rust sweep: every configuration with its deflated Sharpe and OOS/IS ratio. */
function RealSweep({ report }: { report: SweepReport }) {
  const keys = report.rows[0]?.params.map(([k]) => k) ?? [];
  const best = report.rows[0];
  const credible = report.rows.filter((r) => r.pValue < P_BAR && (r.oosIsRatio ?? 0) >= RATIO_BAR).length;
  return (
    <div className="mt-3">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-cyber-text-dim">
        <Badge tone="neutral">{report.trials} configurations tried</Badge>
        <Badge tone="neutral">{report.markets} markets</Badge>
        <Badge tone="neutral">costs: {report.costVenue}</Badge>
        <Badge tone={credible > 0 ? "green" : "red"}>
          {credible} of {report.trials} clear both bars
        </Badge>
      </div>
      <div className="overflow-x-auto">
        <div className="grid min-w-[760px]" style={{ gridTemplateColumns: `repeat(${keys.length}, auto) repeat(6, 1fr)` }}>
          {keys.map((k) => (
            <Head key={k}>{k}</Head>
          ))}
          <Head right>IS Sharpe</Head>
          <Head right>OOS Sharpe</Head>
          <Head right>OOS/IS</Head>
          <Head right>Deflated Sharpe</Head>
          <Head right>OOS net</Head>
          <Head right>OOS trades</Head>
          {report.rows.map((r, i) => (
            <SweepLine key={i} row={r} first={i === 0} />
          ))}
        </div>
      </div>
      <div className="mt-2 text-xs text-cyber-text-faint">
        Ranked by in-sample Sharpe, the way an optimizer without deflation would pick. The top row's deflated Sharpe
        is {best ? `${(best.deflatedSharpe * 100).toFixed(0)}% (p = ${best.pValue.toFixed(3)})` : "n/a"}: below 95%
        (p ≥ {P_BAR}) the best result is not distinguishable from the luckiest of {report.trials} tries on noise.
        OOS net is after costs on the held-out 40 %.
      </div>
    </div>
  );
}

function SweepLine({ row, first }: { row: SweepRow; first: boolean }) {
  const warn = costWarning(row.oos.pnl);
  const significant = row.pValue < P_BAR;
  return (
    <Fragment>
      {row.params.map(([k, v], j) => (
        <Cell key={k} className={first ? "text-accent" : ""}>
          {first && j === 0 ? <Badge tone="purple">top IS</Badge> : null} {v}
        </Cell>
      ))}
      <Cell>{row.is.sharpe.toFixed(2)}</Cell>
      <Cell className={row.oos.sharpe >= 0 ? "text-success" : "text-danger"}>{row.oos.sharpe.toFixed(2)}</Cell>
      <RatioCell ratio={row.oosIsRatio} />
      <Cell className={significant ? "text-success" : "text-danger"}>
        <span title={`p = ${row.pValue.toFixed(3)}`}>
          {(row.deflatedSharpe * 100).toFixed(0)}%
        </span>
      </Cell>
      <Cell className={row.oos.pnl.net >= 0 ? "text-success" : "text-danger"}>
        <span title={warn ?? `gross ${(row.oos.pnl.gross * 100).toFixed(1)}%, costs ${(row.oos.pnl.costs * 100).toFixed(1)}%`}>
          {warn && <AlertTriangle size={11} className="mr-1 inline text-warning" />}
          {(row.oos.pnl.net * 100).toFixed(1)}%
        </span>
      </Cell>
      <Cell>{row.oos.trades}</Cell>
    </Fragment>
  );
}

function RatioCell({ ratio }: { ratio?: number }) {
  if (ratio === undefined) {
    return (
      <Cell className="text-cyber-text-faint">
        <span title="In-sample Sharpe was not positive, so a ratio means nothing">n/a</span>
      </Cell>
    );
  }
  return <Cell className={ratio >= RATIO_BAR ? "text-success" : "text-danger"}>{ratio.toFixed(2)}</Cell>;
}

function WfCol({ title, mc }: { title: string; mc: MonteCarlo }) {
  return (
    <div className="rounded-lg border border-cyber-border bg-cyber-surface-2 p-3">
      <div className="mb-2 text-xs uppercase text-cyber-text-faint">{title}</div>
      <div className="space-y-1 text-sm">
        <Row label="Median return" value={`${mc.medianReturn >= 0 ? "+" : ""}${mc.medianReturn.toFixed(1)}%`} tone={mc.medianReturn >= 0 ? "text-success" : "text-danger"} />
        <Row label="% profitable" value={`${(mc.pctProfitable * 100).toFixed(0)}%`} tone={mc.pctProfitable >= 0.5 ? "text-success" : "text-danger"} />
        <Row label="Median Sharpe" value={mc.medianSharpe.toFixed(2)} tone="text-cyber-text" />
        <Row label="Worst DD" value={`${mc.worstDD.toFixed(1)}%`} tone="text-danger" />
      </div>
    </div>
  );
}
function Row({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-cyber-text-dim">{label}</span>
      <span className={`font-mono ${tone}`}>{value}</span>
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
