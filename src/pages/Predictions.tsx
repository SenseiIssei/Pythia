import { useState } from "react";
import {
  Target,
  Sparkles,
  ShieldCheck,
  TriangleAlert,
  Scale,
  Layers,
  ChevronRight,
  Gauge,
} from "lucide-react";
import { Card, PageHeader, Badge, Button, Meter } from "../components/ui";
import { useStore } from "../store";
import { runEnsemble, canRunEnsemble } from "../predict";
import type { MarketForecast, SourceView, Track } from "../types";

export function Predictions() {
  const { forecasts, tracks, coherence, forecastStats } = useStore();
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState("");

  const events = forecasts.filter((f) => f.kind === "outcome");
  const prices = forecasts.filter((f) => f.kind === "direction");
  const untrusted = forecastStats.trustedSources === 0;

  async function ask(marketId: string) {
    setBusy(marketId);
    setMsg((m) => ({ ...m, [marketId]: "" }));
    try {
      const r = await runEnsemble(marketId, notes);
      setMsg((m) => ({
        ...m,
        [marketId]:
          r.answered > 0
            ? `${r.answered}/${r.asked} models answered${r.errors.length ? ` · ${r.errors.join("; ")}` : ""}`
            : `no model answered — ${r.errors.join("; ") || "check your keys"}`,
      }));
    } catch (e) {
      setMsg((m) => ({ ...m, [marketId]: e instanceof Error ? e.message : String(e) }));
    }
    setBusy(null);
  }

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Predictions"
        subtitle="Ensemble forecasts, scored against the market — Polymarket & directional"
      />

      {/* The single most important thing to understand about this page. */}
      <Card className={`mb-4 ${untrusted ? "border-warning/30 bg-warning/5" : "border-accent/20 bg-accent/5"}`}>
        <div className="flex items-start gap-3">
          {untrusted ? (
            <TriangleAlert size={18} className="mt-0.5 shrink-0 text-warning" />
          ) : (
            <ShieldCheck size={18} className="mt-0.5 shrink-0 text-accent" />
          )}
          <div className="text-sm text-cyber-text-dim">
            <div className={`font-bold ${untrusted ? "text-warning" : "text-accent"}`}>
              {untrusted
                ? "No source has earned any weight yet"
                : `${forecastStats.trustedSources} source(s) have beaten the market and carry weight`}
            </div>
            The market price is the default answer, and every source has to <b>earn</b> a deviation from
            it by beating it on a scored track record. Until one does, the ensemble sits on the market
            price, the edge is ~0, and nothing trades — which is the honest state, not a broken one.
            <div className="mt-1 text-[11px] text-cyber-text-faint">
              {forecastStats.recorded.toLocaleString()} forecasts recorded ·{" "}
              {forecastStats.resolved.toLocaleString()} scored · {forecastStats.pending.toLocaleString()}{" "}
              awaiting resolution
            </div>
          </div>
        </div>
      </Card>

      {coherence.length > 0 && (
        <Card title="Coherence breaks" className="mb-4" right={<Scale size={14} className="text-purple-neon" />}>
          <div className="mb-2 text-sm text-cyber-text-dim">
            A market's own outcomes must price to 1. When they do not, the gap is arithmetic, not a
            forecast — no opinion about the world is involved.
          </div>
          <div className="space-y-1">
            {coherence.map((b) => (
              <div
                key={b.eventId}
                className="flex items-center justify-between gap-3 rounded border border-cyber-border bg-cyber-surface/40 px-3 py-1.5 text-sm"
              >
                <span className="min-w-0 flex-1 truncate">{b.title}</span>
                <span className="font-mono text-xs text-cyber-text-dim">Σ {b.sum.toFixed(4)}</span>
                <span className={`font-mono text-xs ${b.netBps > 0 ? "text-success" : "text-cyber-text-faint"}`}>
                  {b.netBps > 0 ? "+" : ""}
                  {b.netBps.toFixed(0)}bps net
                </span>
                <Badge tone={b.actionable ? "green" : "neutral"}>
                  {b.actionable ? "actionable" : b.kind === "overpriced" ? "needs shorting" : "below costs"}
                </Badge>
              </div>
            ))}
          </div>
        </Card>
      )}

      {canRunEnsemble() && (
        <Card className="mb-4" title="Context for the models" right={<Sparkles size={14} className="text-purple-neon" />}>
          <div className="mb-2 text-sm text-cyber-text-dim">
            Optional. Passed verbatim and identically to every model, so any disagreement between them
            measures the question rather than the prompt.
          </div>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            placeholder="e.g. CPI print came in at 2.9% this morning; the committee meets on the 18th"
            className="w-full rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
          />
        </Card>
      )}

      <Section
        title="Event markets"
        subtitle="P(YES) — the question a model can actually reason about"
        forecasts={events}
        open={open}
        setOpen={setOpen}
        onAsk={ask}
        busy={busy}
        msg={msg}
      />
      <Section
        title="Directional markets"
        subtitle="P(price higher over the forecast horizon) — resolves on a timer, which is where the calibration data comes from"
        forecasts={prices}
        open={open}
        setOpen={setOpen}
        onAsk={ask}
        busy={busy}
        msg={msg}
      />

      {tracks.length > 0 && <Scoreboard tracks={tracks} />}
    </div>
  );
}

function Section({
  title,
  subtitle,
  forecasts,
  open,
  setOpen,
  onAsk,
  busy,
  msg,
}: {
  title: string;
  subtitle: string;
  forecasts: MarketForecast[];
  open: string | null;
  setOpen: (v: string | null) => void;
  onAsk: (id: string) => Promise<void>;
  busy: string | null;
  msg: Record<string, string>;
}) {
  if (forecasts.length === 0) return null;
  // Biggest net edge first — that is the only ordering that matters here.
  const sorted = [...forecasts].sort((a, b) => b.netEdgeBps - a.netEdgeBps);

  return (
    <Card title={title} className="mb-4" right={<Target size={14} className="text-accent" />}>
      <div className="mb-3 text-[11px] text-cyber-text-faint">{subtitle}</div>
      <div className="space-y-1">
        {sorted.map((f) => (
          <div key={f.marketId} className="rounded border border-cyber-border bg-cyber-surface/40">
            <button
              onClick={() => setOpen(open === f.marketId ? null : f.marketId)}
              className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-cyber-surface/70"
            >
              <ChevronRight
                size={13}
                className={`shrink-0 text-cyber-text-faint transition-transform ${open === f.marketId ? "rotate-90" : ""}`}
              />
              <span className="min-w-0 flex-1 truncate">{f.symbol}</span>
              <span className="hidden font-mono text-xs text-cyber-text-faint sm:inline">
                mkt {pct(f.marketP)}
              </span>
              <span className="font-mono text-xs">
                → <span className="font-bold">{pct(f.ensembleP)}</span>
              </span>
              <span
                className={`w-20 text-right font-mono text-xs ${
                  f.netEdgeBps > 0 ? "text-success" : "text-cyber-text-faint"
                }`}
              >
                {f.netEdgeBps > 0 ? "+" : ""}
                {f.netEdgeBps.toFixed(0)}bps
              </span>
              <Badge tone={f.action === "buy" ? "green" : f.action === "sell" ? "red" : "neutral"}>
                {f.action}
              </Badge>
            </button>

            {open === f.marketId && (
              <Detail f={f} onAsk={onAsk} busy={busy === f.marketId} msg={msg[f.marketId]} />
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

function Detail({
  f,
  onAsk,
  busy,
  msg,
}: {
  f: MarketForecast;
  onAsk: (id: string) => Promise<void>;
  busy: boolean;
  msg?: string;
}) {
  return (
    <div className="border-t border-cyber-border px-3 py-3">
      <div className="mb-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <Stat label="Market" value={pct(f.marketP)} />
        <Stat label="Pooled sources" value={pct(f.modelP)} />
        <Stat label="Ensemble" value={pct(f.ensembleP)} strong />
        <Stat label="Kelly stake" value={`${(f.kelly * 100).toFixed(2)}%`} />
      </div>

      <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Gauge2 label="Trust in the pool" value={f.trust} hint="how far it may pull from the market" />
        <Gauge2
          label="Disagreement"
          value={Math.min(f.disagreement / 3, 1)}
          hint={`${f.disagreement.toFixed(2)} in log-odds`}
        />
        <Gauge2
          label="Effective sources"
          value={Math.min(f.effectiveSources / 5, 1)}
          hint={`${f.effectiveSources.toFixed(1)} of ${f.sources.length} — agreement is not independence`}
        />
      </div>

      <div className="mb-3 rounded border border-cyber-border/60 bg-cyber-bg/40 px-3 py-2 text-xs text-cyber-text-dim">
        <span className="font-bold uppercase tracking-widest text-cyber-text-faint">Verdict</span>{" "}
        {f.reason}
        <div className="mt-1 text-[11px] text-cyber-text-faint">
          gross edge {f.edgeBps.toFixed(0)}bps − {f.costBps.toFixed(0)}bps round-trip cost ={" "}
          {f.netEdgeBps.toFixed(0)}bps net
        </div>
      </div>

      {f.sources.length > 0 ? (
        <div className="space-y-1">
          {f.sources.map((s) => (
            <SourceRow key={s.source} s={s} />
          ))}
        </div>
      ) : (
        <div className="text-xs text-cyber-text-faint">No source produced an opinion for this market.</div>
      )}

      {canRunEnsemble() && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button tone="purple" icon={Sparkles} disabled={busy} onClick={() => void onAsk(f.marketId)}>
            {busy ? "Asking models…" : "Ask the model ensemble"}
          </Button>
          <span className="text-[11px] text-cyber-text-faint">
            one API call per configured provider
          </span>
          {msg && <span className="text-xs text-cyber-text-dim">{msg}</span>}
        </div>
      )}
    </div>
  );
}

function SourceRow({ s }: { s: SourceView }) {
  const silenced = s.weight <= 0;
  return (
    <div className="rounded border border-cyber-border/60 bg-cyber-bg/30 px-3 py-1.5">
      <div className="flex items-center gap-2 text-sm">
        <Layers size={11} className="shrink-0 text-cyber-text-faint" />
        <span className="font-mono text-xs">{s.source}</span>
        <span className="font-mono text-xs text-cyber-text-dim">{pct(s.p)}</span>
        {Math.abs(s.p - s.rawP) > 0.005 && (
          <span className="text-[10px] text-cyber-text-faint">(said {pct(s.rawP)}, recalibrated)</span>
        )}
        <span className="flex-1" />
        <Badge tone={s.trust > 0 ? "green" : silenced ? "red" : "neutral"}>
          {s.trust > 0 ? `trust ${s.trust.toFixed(2)}` : silenced ? "silenced" : "unproven"}
        </Badge>
        <span className="w-16 text-right text-[10px] text-cyber-text-faint">n={s.n}</span>
      </div>
      {s.rationale && (
        <div className="mt-0.5 pl-5 text-[11px] leading-snug text-cyber-text-faint">{s.rationale}</div>
      )}
    </div>
  );
}

/** The scoreboard that decides everything else on this page. */
function Scoreboard({ tracks }: { tracks: Track[] }) {
  const sorted = [...tracks].sort((a, b) => b.brierSkill - a.brierSkill);
  return (
    <Card title="Source scoreboard" right={<Gauge size={14} className="text-accent" />}>
      <div className="mb-3 text-sm text-cyber-text-dim">
        Brier score against reality, compared with the market's score on <b>the same questions</b>.
        Positive skill is the only thing that earns weight — a confident rationale earns nothing.
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] uppercase tracking-widest text-cyber-text-faint">
              <th className="py-1 text-left font-normal">Source</th>
              <th className="py-1 text-left font-normal">Question</th>
              <th className="py-1 text-right font-normal">n</th>
              <th className="py-1 text-right font-normal">Brier</th>
              <th className="py-1 text-right font-normal">Market</th>
              <th className="py-1 text-right font-normal">Skill</th>
              <th className="py-1 text-right font-normal">Bias</th>
              <th className="py-1 text-right font-normal">Trust</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((t) => {
              const bias = t.score.meanForecast - t.score.meanOutcome;
              return (
                <tr key={`${t.source}-${t.kind}`} className="border-t border-cyber-border/50">
                  <td className="py-1 font-mono text-xs">{t.source}</td>
                  <td className="py-1 text-xs text-cyber-text-faint">{t.kind}</td>
                  <td className="py-1 text-right font-mono text-xs">{t.score.n}</td>
                  <td className="py-1 text-right font-mono text-xs">{t.score.brier.toFixed(4)}</td>
                  <td className="py-1 text-right font-mono text-xs text-cyber-text-faint">
                    {t.marketScore.brier.toFixed(4)}
                  </td>
                  <td
                    className={`py-1 text-right font-mono text-xs ${
                      t.brierSkill > 0 ? "text-success" : "text-danger"
                    }`}
                  >
                    {(t.brierSkill * 100).toFixed(1)}%
                  </td>
                  <td className="py-1 text-right font-mono text-xs text-cyber-text-dim">
                    {bias > 0 ? "+" : ""}
                    {(bias * 100).toFixed(1)}pp
                  </td>
                  <td className="py-1 text-right font-mono text-xs">
                    {t.trust > 0 ? t.trust.toFixed(2) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-2 text-[11px] leading-snug text-cyber-text-faint">
        <b>Brier</b>: mean squared error against the 0/1 outcome — 0.25 is what always saying 50% scores.{" "}
        <b>Skill</b>: how much better than the market on the same questions. <b>Bias</b>: systematic
        over- or under-forecasting. <b>Trust</b>: skill discounted by how little evidence there is for it.
      </div>
    </Card>
  );
}

function Stat({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-widest text-cyber-text-faint">{label}</div>
      <div className={`font-mono ${strong ? "text-base font-bold text-glow" : "text-sm"}`}>{value}</div>
    </div>
  );
}

function Gauge2({ label, value, hint }: { label: string; value: number; hint: string }) {
  return (
    <div className="rounded border border-cyber-border/60 bg-cyber-bg/30 px-3 py-2">
      <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-widest text-cyber-text-faint">
        <span>{label}</span>
        <span className="font-mono">{(value * 100).toFixed(0)}%</span>
      </div>
      <Meter pct={Math.max(0, Math.min(1, value)) * 100} />
      <div className="mt-1 text-[10px] text-cyber-text-faint">{hint}</div>
    </div>
  );
}

function pct(p: number): string {
  return `${(p * 100).toFixed(1)}%`;
}
