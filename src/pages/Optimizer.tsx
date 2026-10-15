import { useMemo, useState } from "react";
import { AlertTriangle, GitBranch, Play, Sparkles } from "lucide-react";
import { useStore } from "../store";
import { Badge, Button, Field, List, Notice, Page, Spinner, changeTone, inputCls, signedPct, signedRatio } from "../design";
import { KeyStats, More, Row, Section, pct, plural, share } from "../pagekit";
import { explain } from "../glossary";
import { P_BAR, RATIO_BAR, credibleCount, degradationText, paramLine, ratioWord } from "../pagekit/riskLab";
import { autoGrid, monteCarlo, sweep, walkForward, type SweepPoint, type MonteCarlo, type WalkForward } from "../engine/optimize";
import { researchAvailable, runSweep } from "../research";
import { costWarning } from "../components/PnlBreakdown";
import type { SweepReport, SweepRow } from "../types";

/** Rows shown before the rest fold away. */
const SHOWN = 10;

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
    <Page title="Optimizer" subtitle="Tries many settings for a strategy, and puts every result next to the two numbers that say how much of it to believe.">
      <Section title="Strategy" hint="The settings it tries come from this strategy's own parameters.">
        <Field label="Strategy">
          <select
            value={strat?.id ?? ""}
            onChange={(e) => {
              setStratId(e.target.value);
              setReal(null);
              setPoints(null);
            }}
            className={inputCls}
          >
            {testable.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </Field>
        <List className="mt-3">
          <Row
            label="Deflated Sharpe"
            sub="How likely a result is real edge given how many settings were tried. The best of many tries on pure noise always looks good."
            value="95% or more"
            valueSub="to believe it"
          />
          <Row
            label="OOS/IS"
            sub="The result on data the ranking never saw, against the data it was chosen on. Below the bar the settings are mostly noise."
            value={`${RATIO_BAR} or more`}
            valueSub="to believe it"
          />
        </List>
      </Section>

      <Section title="Real candles" hint="A sweep on real daily price history, run by the engine in the desktop app.">
        {canResearch ? (
          <>
            <Button variant="primary" icon={Play} onClick={() => void runReal()} disabled={!strat || realBusy}>
              {realBusy ? "Sweeping" : "Sweep on real candles"}
            </Button>
            <p className="mt-3 text-[13px] leading-relaxed text-muted">Daily candles. Fit on the first 60 %, hold out the last 40 %. Costs from config/costs.json.</p>
            {realBusy && (
              <div className="mt-3">
                <Spinner>Running every setting on real history. This can take a minute.</Spinner>
              </div>
            )}
            {realErr && (
              <Notice tone="danger" title="The sweep failed" className="mt-3">
                <span className="break-words">{realErr}</span>
              </Notice>
            )}
            {real && <RealSweep report={real} />}
          </>
        ) : (
          <p className="text-[13px] leading-relaxed text-muted">
            Real-candle sweeps run in the Rust core, which this browser build does not have. Open the desktop app or connect a backend (VITE_PYTHIA_SERVER) to get
            deflated Sharpe on real history. The simulated sweep below shows the mechanics; it is not evidence.
          </p>
        )}
      </Section>

      <Section title="Simulated demo" hint="The same search on made-up price histories. Good for seeing how it works, not for deciding anything.">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <NumField label="Seeds per setting" value={seeds} onChange={setSeeds} step={1} min={4} max={40} />
          <NumField label="Bars" value={bars} onChange={setBars} step={100} min={300} max={2000} />
          <NumField label="Volatility" value={vol} onChange={setVol} step={0.001} min={0.005} max={0.05} />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="secondary" icon={Sparkles} onClick={run} disabled={!strat || running}>
            {running ? "Optimizing" : "Run simulated sweep"}
          </Button>
          <Button variant="secondary" icon={GitBranch} onClick={runWalkForward} disabled={!strat || running}>
            Walk-forward test
          </Button>
        </div>
        <p className="mt-3 break-words text-[13px] leading-relaxed text-muted">
          Tries every combination of {paramKeys.join(", ") || "the settings"}, each on {seeds} random histories, then re-runs it on {seeds} histories it never saw.
        </p>
      </Section>

      {wf && <WalkForwardResult wf={wf} />}

      {mc && (
        <KeyStats
          items={[
            { label: "Median Return", value: signedPct(mc.medianReturn, 1), tone: changeTone(mc.medianReturn), sub: `Best settings, across ${plural(mc.seeds, "seed")}` },
            {
              label: "% Profitable",
              value: share(mc.pctProfitable),
              tone: mc.pctProfitable >= 0.5 ? "up" : "down",
              sub: `Median Sharpe ${mc.medianSharpe.toFixed(2)}`,
            },
            { label: "Worst Drawdown", value: pct(mc.worstDD, 1), sub: `Worst ${signedPct(mc.worstReturn, 0)}, best ${signedPct(mc.bestReturn, 0)}` },
          ]}
        />
      )}

      {points && (
        <Section title="Simulated sweep, ranked by robustness" hint="Every combination of settings, the steadiest first, not the luckiest. The number on the right is the median return.">
          <List>
            {points.slice(0, 15).map((p, i) => (
              <SimLine key={i} p={p} best={i === 0} />
            ))}
          </List>
          <p className="mt-3 text-[13px] leading-relaxed text-muted">
            Ranked by a robustness score (median return × consistency − drawdown penalty). The OOS numbers re-run each combination on random histories the ranking
            never saw. Simulated data, so a filter, not a promise: the deflated Sharpe lives in the real-candle sweep above.
          </p>
          <Terms keys={["Median Return", "Median Sharpe", "% Profitable", "Worst Drawdown", "OOS Sharpe", "OOS/IS"]} />
        </Section>
      )}
    </Page>
  );
}

function SimLine({ p, best }: { p: SweepPoint; best: boolean }) {
  const r = ratioWord(p.oosIsRatio);
  return (
    <Row
      label={
        <span className="flex flex-wrap items-center gap-1.5">
          {best && <Badge tone="good">Best</Badge>}
          <span className="break-all">{paramLine(p.params)}</span>
        </span>
      }
      sub={
        <span className="tabular">
          Sharpe {p.medianSharpe.toFixed(2)} · {share(p.pctProfitable)} profitable · worst dip {pct(p.worstDD, 1)} ·{" "}
          OOS Sharpe {p.oosMedianSharpe.toFixed(2)} ·{" "}
          <span className={r.good === null ? "" : r.good ? "text-up" : "text-down"} title={r.good === null ? "In-sample Sharpe was not positive, so a ratio means nothing" : undefined}>
              OOS/IS {r.text}
            </span>
          {" "}
          ·{" "}
          <span title="Deflated Sharpe is computed by the Rust core on real candles. Synthetic random histories are not a sample it can deflate honestly.">
            deflated: real only
          </span>
        </span>
      }
      value={signedPct(p.medianReturn, 1)}
      tone={changeTone(p.medianReturn)}
    />
  );
}

/** The walk-forward check: settings chosen on one batch, tested on another. */
function WalkForwardResult({ wf }: { wf: WalkForward }) {
  return (
    <Section
      title="Walk-forward check"
      help="Settings chosen on one batch of histories, then tested on a separate batch they never saw."
      hint={
        <>
          Best settings <span className="break-all font-semibold text-ink">{paramLine(wf.best)}</span>, chosen on one batch of histories, then tested on a
          separate batch they never saw.
        </>
      }
      right={<Badge tone={wf.holdsUp ? "good" : "bad"}>{wf.holdsUp ? "Holds up on new data" : "Likely overfit"}</Badge>}
    >
      <div className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
        <WfCol title="Chosen on (in-sample)" mc={wf.inSample} />
        <WfCol title="Never seen (out-of-sample)" mc={wf.outOfSample} />
      </div>
      <Notice tone={wf.holdsUp ? "success" : "warning"} className="mt-3">
        Change from the first batch to the new one:{" "}
        <span className={`tabular font-semibold ${wf.degradationPct > 2 ? "text-down" : "text-up"}`}>{degradationText(wf.degradationPct)}</span>.
        {wf.holdsUp
          ? " The edge survived data it never saw: a real, if modest, signal by this test."
          : " The edge mostly vanished on data it never saw. That is classic overfitting: do not trust it."}
      </Notice>
    </Section>
  );
}

function WfCol({ title, mc }: { title: string; mc: MonteCarlo }) {
  return (
    <div className="min-w-0">
      <h3 className="pt-2 text-[13px] font-semibold text-muted">{title}</h3>
      <List>
        <Row label="Median return" value={signedPct(mc.medianReturn, 1)} tone={changeTone(mc.medianReturn)} help="" />
        <Row label="Profitable" value={share(mc.pctProfitable)} tone={mc.pctProfitable >= 0.5 ? "up" : "down"} help="" />
        <Row label="Median Sharpe" value={mc.medianSharpe.toFixed(2)} />
        <Row label="Worst dip" value={pct(mc.worstDD, 1)} help="" />
      </List>
    </div>
  );
}

/** The Rust sweep: every configuration with its deflated Sharpe and OOS/IS ratio. */
function RealSweep({ report }: { report: SweepReport }) {
  const best = report.rows[0];
  const credible = credibleCount(report.rows);
  const top = report.rows.slice(0, SHOWN);
  const rest = report.rows.slice(SHOWN);
  return (
    <div className="mt-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge>{plural(report.trials, "configuration")} tried</Badge>
        <Badge>{plural(report.markets, "market")}</Badge>
        <Badge>Costs: {report.costVenue}</Badge>
        <Badge tone={credible > 0 ? "good" : "bad"}>
          {credible} of {report.trials} clear both bars
        </Badge>
      </div>
      <p className="mt-3 text-[13px] leading-relaxed text-muted">
        Ranked by in-sample Sharpe, the way an optimizer without deflation would pick. The number on the right is the deflated Sharpe, with what the held-out 40 %
        made after costs under it.
      </p>
      <List className="mt-1">
        {top.map((r, i) => (
          <SweepLine key={i} row={r} first={i === 0} />
        ))}
      </List>
      {rest.length > 0 && (
        <More title={`The other ${plural(rest.length, "configuration")}`}>
          <List>
            {rest.map((r, i) => (
              <SweepLine key={i} row={r} first={false} />
            ))}
          </List>
        </More>
      )}
      <p className="mt-3 text-[13px] leading-relaxed text-muted">
        The top row's deflated Sharpe is {best ? `${share(best.deflatedSharpe)} (p = ${best.pValue.toFixed(3)})` : "n/a"}: below 95% (p ≥ {P_BAR}) the best result is
        not distinguishable from the luckiest of {report.trials} tries on noise. OOS net is after costs on the held-out 40 %.
      </p>
      <Terms keys={["IS Sharpe", "OOS Sharpe", "OOS/IS", "Deflated Sharpe", "OOS net"]} />
    </div>
  );
}

function SweepLine({ row, first }: { row: SweepRow; first: boolean }) {
  const warn = costWarning(row.oos.pnl);
  const significant = row.pValue < P_BAR;
  const r = ratioWord(row.oosIsRatio);
  return (
    <Row
      label={
        <span className="flex flex-wrap items-center gap-1.5">
          {first && <Badge tone="accent">Top in-sample</Badge>}
          <span className="break-all">{paramLine(row.params)}</span>
        </span>
      }
      sub={
        <span className="tabular">
          IS Sharpe {row.is.sharpe.toFixed(2)} ·{" "}
          <span className={row.oos.sharpe >= 0 ? "text-up" : "text-down"}>OOS Sharpe {row.oos.sharpe.toFixed(2)}</span>
          {" "}
          ·{" "}
          <span className={r.good === null ? "" : r.good ? "text-up" : "text-down"} title={r.good === null ? "In-sample Sharpe was not positive, so a ratio means nothing" : undefined}>
              OOS/IS {r.text}
            </span>
          {" "}
          · {plural(row.oos.trades, "OOS trade")} · p = {row.pValue.toFixed(3)}
        </span>
      }
      value={
        <span title={`p = ${row.pValue.toFixed(3)}`} className={significant ? "text-up" : "text-down"}>
          {share(row.deflatedSharpe)}
        </span>
      }
      valueSub={
        <span className="block">
          <span className="block text-[11px]">{significant ? "likely real" : "could be luck"}</span>
          <span
            className={`tabular inline-flex items-center gap-1 ${row.oos.pnl.net >= 0 ? "text-up" : "text-down"}`}
            title={warn ?? `gross ${signedRatio(row.oos.pnl.gross, 1)}, costs ${share(row.oos.pnl.costs, 1)}`}
          >
            {warn && <AlertTriangle size={12} aria-label="Costs are eating the result" className="text-warn" />}
            net {signedRatio(row.oos.pnl.net, 1)}
          </span>
        </span>
      }
    />
  );
}

/** The words in the rows, each with its plain meaning, folded away. */
function Terms({ keys }: { keys: string[] }) {
  return (
    <More title="What the numbers mean">
      <dl className="divide-y divide-line">
        {keys.map((k) => (
          <div key={k} className="py-2.5">
            <dt className="text-[15px] text-ink">{k}</dt>
            <dd className="mt-0.5 text-[13px] leading-snug text-muted">{explain(k) ?? ""}</dd>
          </div>
        ))}
      </dl>
    </More>
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
