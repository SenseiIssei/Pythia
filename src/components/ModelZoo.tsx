import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Badge, Card, Sparkline } from "./ui";
import { ago, driftTone, edgeSeries, fmtScore, statusTone, winShare, type ZooModel, type ZooStatus } from "../zoo";

const signed = (v: number | null | undefined, dp = 1) =>
  v === null || v === undefined || !Number.isFinite(v) ? "n/a" : `${v >= 0 ? "+" : ""}${v.toFixed(dp)} %`;

/** Every model the lab keeps, one row each; a row opens to its history, live score and drift. */
export function ModelZoo({ z }: { z: ZooStatus }) {
  const [open, setOpen] = useState<string | null>(null);
  const drifting = z.models.filter((m) => m.drift?.level === "drift");
  return (
    <Card title="All models" right={<span className="text-xs text-cyber-text-faint">lab report of {z.generated}</span>}>
      <p className="mb-3 text-sm text-cyber-text-dim">
        Each model has to beat a plain baseline out of sample before anything may use it. Scores are walk-forward (each
        quarter predicted by a model that never saw it) and, since it went live, scored in shadow every day.
      </p>
      {drifting.length > 0 && (
        <p className="mb-3 text-sm text-danger">
          {drifting.map((m) => m.code).join(", ")}: inputs outside the range the model was trained on. Forecasts may be
          off until the next retrain.
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-cyber-text-faint">
              <th className="py-1.5 pr-3">Model</th>
              <th className="py-1.5 pr-3">Status</th>
              <th className="py-1.5 pr-3 text-right">vs baseline</th>
              <th className="py-1.5 pr-3">Over time</th>
              <th className="py-1.5 pr-3 text-right">Live</th>
              <th className="py-1.5 pr-3">Retrained</th>
              <th className="py-1.5 pr-3">Drift</th>
              <th className="py-1.5">Used by</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {z.models.map((m) => (
              <ZooRow key={m.code} m={m} open={open === m.code} toggle={() => setOpen(open === m.code ? null : m.code)} />
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function ZooRow({ m, open, toggle }: { m: ZooModel; open: boolean; toggle: () => void }) {
  const edge = edgeSeries(m.history, m.higherBetter);
  const vs = m.higherBetter
    ? m.modelScore !== null && m.baselineScore !== null
      ? `${fmtScore(m.modelScore, m.metric)} vs ${fmtScore(m.baselineScore, m.metric)}`
      : "n/a"
    : signed(m.gainPct);
  const live = m.live && m.live.rows > 0 ? `${signed(m.live.gainPct)} · ${m.live.rows}` : m.live?.open ? `${m.live.open} open` : "n/a";
  return (
    <>
      <tr className="cursor-pointer border-t border-cyber-border hover:bg-white/5" onClick={toggle}>
        <td className="py-1.5 pr-3">
          <span className="flex items-center gap-1.5 font-medium text-cyber-text">
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            {m.code} <span className="font-normal text-cyber-text-dim">{m.title}</span>
          </span>
        </td>
        <td className="py-1.5 pr-3">
          <Badge tone={statusTone(m.status)}>{m.status}</Badge>
        </td>
        <td className={`py-1.5 pr-3 text-right ${m.gate?.passed ? "text-success" : "text-cyber-text-dim"}`}>{vs}</td>
        <td className="w-28 py-1.5 pr-3">
          {edge.length >= 2 ? (
            <Sparkline data={edge} height={22} tone="cyan" label={`${m.code} edge over its baseline per period`} />
          ) : (
            <span className="text-xs text-cyber-text-faint">n/a</span>
          )}
        </td>
        <td className="py-1.5 pr-3 text-right text-cyber-text-dim">{live}</td>
        <td className="py-1.5 pr-3 text-cyber-text-dim">{m.managedBy === "retired" ? "retired" : ago(m.lastRetrainMs)}</td>
        <td className="py-1.5 pr-3">
          {m.drift ? <Badge tone={driftTone(m.drift.level)}>{m.drift.level}</Badge> : <span className="text-xs text-cyber-text-faint">{m.shadowWhere === "engine" ? "in engine" : "n/a"}</span>}
        </td>
        <td className="py-1.5 text-cyber-text-dim">{m.usedBy.length ? m.usedBy.join(", ") : "none"}</td>
      </tr>
      {open && (
        <tr className="border-t border-cyber-border/50">
          <td colSpan={8} className="py-3">
            <ZooDetail m={m} edge={edge} />
          </td>
        </tr>
      )}
    </>
  );
}

function ZooDetail({ m, edge }: { m: ZooModel; edge: number[] }) {
  const won = winShare(m.history, m.higherBetter);
  const weeks = m.live?.weeks ?? [];
  const liveEdge = edgeSeries(weeks, m.higherBetter);
  const today = (m.extra?.today ?? null) as unknown;
  return (
    <div className="space-y-3 text-sm text-cyber-text-dim">
      <p>
        <span className="text-cyber-text">Forecasts</span> {m.target} ({m.horizon}, {m.universe}). Scored by{" "}
        <span className="text-accent">{m.metric}</span> against {m.baseline}.
      </p>
      <p>{m.statusDetail}</p>
      {m.gate && (
        <p>
          Gate <Badge tone={m.gate.passed ? "green" : "amber"}>{m.gate.passed ? "passed" : "failed"}</Badge> {m.gate.why}
        </p>
      )}
      {edge.length >= 2 && (
        <div>
          <div className="mb-1 text-xs text-cyber-text-faint">
            Better than the baseline, % per {m.managedBy === "zoo" ? "walk-forward period" : "retrain"}
            {won !== null && ` (won ${(won * 100).toFixed(0)} % of ${edge.length})`}
          </div>
          <Sparkline data={edge} height={48} tone="cyan" label={`${m.code} edge per period`} />
        </div>
      )}
      {m.live && m.live.rows > 0 && (
        <div>
          <div className="mb-1 text-xs text-cyber-text-faint">
            Live in shadow since {m.live.since}: {m.live.rows} forecasts scored, {signed(m.live.gainPct)} against the
            baseline, closer in {((m.live.winRate ?? 0) * 100).toFixed(0)} % of them
          </div>
          {liveEdge.length >= 2 && <Sparkline data={liveEdge} height={36} tone="purple" label={`${m.code} live edge per week`} />}
        </div>
      )}
      {m.live?.error && <p className="text-danger">Shadow scoring failed: {m.live.error}</p>}
      {m.drift && m.drift.features.length > 0 && (
        <div>
          <div className="mb-1 text-xs text-cyber-text-faint">{m.drift.why}</div>
          <div className="flex flex-wrap gap-1.5">
            {m.drift.features.slice(0, 12).map((f) => (
              <span key={f.feature} title={`${f.outsidePct.toFixed(1)} % outside the trained range, PSI ${f.psi.toFixed(2)}`}>
                <Badge tone={driftTone(f.level)}>{f.feature}</Badge>
              </span>
            ))}
          </div>
        </div>
      )}
      {Array.isArray(today) && today.length > 0 && <TodayTable rows={today as Record<string, number | string>[]} />}
      {today !== null && !Array.isArray(today) && typeof today === "object" && (
        <p>
          Today:{" "}
          {Object.entries(today as Record<string, unknown>)
            .map(([k, v]) => `${k} ${typeof v === "number" ? v.toFixed(2) : String(v)}`)
            .join(", ")}
        </p>
      )}
      {m.decisions.length > 0 && (
        <div>
          <div className="mb-1 text-xs text-cyber-text-faint">Champion and challenger</div>
          <ul className="space-y-1">
            {m.decisions
              .slice(-5)
              .reverse()
              .map((d, i) => (
                <li key={i}>
                  <span className="text-cyber-text">{d.date}</span> {d.decision}: {d.why}
                </li>
              ))}
          </ul>
        </div>
      )}
      <p>
        <span className="text-cyber-text">Use:</span> {m.useRule || "not decided"}
        {m.nextDue && m.managedBy !== "retired" && ` Next retrain: ${m.nextDue}.`}
      </p>
    </div>
  );
}

function TodayTable({ rows }: { rows: Record<string, number | string>[] }) {
  const cols = Object.keys(rows[0]).filter((k) => k !== "symbol");
  return (
    <div className="overflow-x-auto">
      <div className="mb-1 text-xs text-cyber-text-faint">Latest forecasts (shadow, not traded)</div>
      <table className="text-xs">
        <thead>
          <tr className="text-left text-cyber-text-faint">
            <th className="pr-3">Coin</th>
            {cols.map((c) => (
              <th key={c} className="pr-3 text-right">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="pr-3 text-cyber-text">{String(r.symbol ?? "")}</td>
              {cols.map((c) => (
                <td key={c} className="pr-3 text-right">
                  {typeof r[c] === "number" ? (c === "p_up" ? `${((r[c] as number) * 100).toFixed(0)} %` : `${((r[c] as number) * 100).toFixed(2)} %`) : String(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
