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
import {
  Card,
  PageHeader,
  Badge,
  Button,
  EmptyState,
  Explain,
  Field,
  Meter,
  Notice,
  Readout,
  Term,
  inputCls,
} from "../components/ui";
import { explain } from "../glossary";
import { liveMode } from "../live";
import { useStore } from "../store";
import { runEnsemble, canRunEnsemble } from "../predict";
import { useAdvanced } from "../uiMode";
import type { MarketForecast, SourceView, Track } from "../types";

export function Predictions() {
  const { forecasts, tracks, coherence, forecastStats } = useStore();
  const advanced = useAdvanced();
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
            : `no model answered: ${r.errors.join("; ") || "check your keys"}`,
      }));
    } catch (e) {
      setMsg((m) => ({ ...m, [marketId]: e instanceof Error ? e.message : String(e) }));
    }
    setBusy(null);
  }

  const header = (
    <PageHeader
      title="Predictions"
      subtitle={
        advanced
          ? "Ensemble forecasts scored against the market: Polymarket events and price direction."
          : "What Pythia thinks will happen, next to what everyone else thinks, and whether it has earned the right to act on it."
      }
    />
  );

  // The forecasting layer lives in the Rust core. The browser demo has none, so
  // say that instead of showing an empty page.
  if (liveMode() === "none" && forecasts.length === 0) {
    return (
      <div className="animate-fade-in mx-auto max-w-4xl">
        {header}
        <Card>
          <EmptyState icon={Target} title="Predictions need the desktop app or a connected server">
            Forecasts are made, written down and scored by the engine in the desktop app or on a backend server. This
            browser version only practises trading with fake money, so there is nothing to show here yet.
          </EmptyState>
        </Card>
      </div>
    );
  }

  return (
    <div className="animate-fade-in mx-auto max-w-4xl space-y-4">
      {header}

      {/* The single most important thing to understand about this page. */}
      <Notice
        tone={untrusted ? "warning" : "success"}
        icon={untrusted ? TriangleAlert : ShieldCheck}
        title={
          untrusted
            ? advanced
              ? "No source has earned any weight yet"
              : "It is still learning, so it does not bet on its own opinions"
            : `${forecastStats.trustedSources} source${forecastStats.trustedSources === 1 ? " has" : "s have"} beaten the market and carr${forecastStats.trustedSources === 1 ? "ies" : "y"} weight`
        }
      >
        {advanced ? (
          <>
            The market price is the default answer, and every source has to <b>earn</b> a deviation from it by beating
            it on a scored track record. Until one does, the ensemble sits on the market price, the edge is about zero,
            and nothing trades. That is the honest state, not a broken one.
          </>
        ) : (
          <>
            The price a market trades at is everyone's combined guess. Pythia only moves away from it once one of its
            sources has beaten that guess on a checked record. Until then it mostly agrees with the market and makes no
            bets, on purpose.
          </>
        )}
        <div className="mt-1.5 font-mono text-[11px] text-cyber-text-faint">
          {forecastStats.recorded.toLocaleString()} forecasts written down · {forecastStats.resolved.toLocaleString()}{" "}
          checked · {forecastStats.pending.toLocaleString()} waiting for the outcome
        </div>
      </Notice>

      {/* Coherence is an arbitrage table. Real, but meaningless without knowing
          what a leg and a basis point are. */}
      {advanced && coherence.length > 0 && (
        <Card
          title="Coherence breaks"
          icon={Scale}
          subtitle="A market's own outcomes must price to 1. When they do not, the gap is arithmetic, not a forecast: no opinion about the world is involved."
        >
          <div className="space-y-1.5">
            {coherence.map((b) => (
              <div
                key={b.eventId}
                className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-lg border border-cyber-border bg-cyber-bg/40 px-3 py-2 text-sm"
              >
                <span className="min-w-0 flex-1 basis-48 truncate">{b.title}</span>
                <span className="font-mono text-xs text-cyber-text-dim" title="Sum of the outcome prices">
                  Σ {b.sum.toFixed(4)}
                </span>
                <span className={`font-mono text-xs ${b.netBps > 0 ? "text-success" : "text-cyber-text-faint"}`}>
                  {b.netBps > 0 ? "+" : ""}
                  {b.netBps.toFixed(0)} <Term k="bps">bps</Term> net
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
        <Card title={advanced ? "Context for the models" : "Something the AI models should know"} icon={Sparkles}>
          <Field
            label="Notes (optional)"
            hint="Passed word for word to every model, so any disagreement between them measures the question rather than the wording."
          >
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              placeholder="e.g. CPI print came in at 2.9% this morning; the committee meets on the 18th"
              className={inputCls}
            />
          </Field>
        </Card>
      )}

      {events.length === 0 && prices.length === 0 && (
        <Card>
          <EmptyState icon={Target} title="No forecasts yet">
            Prediction markets usually arrive within a few seconds of starting. If this stays empty, check that the
            engine is running on the Home page.
          </EmptyState>
        </Card>
      )}

      <Section
        title={advanced ? "Event markets" : "Will this happen?"}
        subtitle={
          advanced
            ? "P(YES): the question a model can actually reason about."
            : "How likely each thing is, according to everyone else (left) and according to Pythia (right). Tap a row for the reasons."
        }
        forecasts={events}
        open={open}
        setOpen={setOpen}
        onAsk={ask}
        busy={busy}
        msg={msg}
        advanced={advanced}
      />
      <Section
        title={advanced ? "Directional markets" : "Will this go up?"}
        subtitle={
          advanced
            ? "P(price higher over the forecast horizon). Resolves on a timer, which is where the calibration data comes from."
            : "Chance the price is higher a while from now. 50% means it has no idea, which is usually the honest answer."
        }
        forecasts={prices}
        open={open}
        setOpen={setOpen}
        onAsk={ask}
        busy={busy}
        msg={msg}
        advanced={advanced}
      />

      {/* The scoreboard is the most important thing on this page and the least
          readable without the vocabulary. Advanced only. */}
      {advanced && tracks.length > 0 && <Scoreboard tracks={tracks} />}
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
  advanced,
}: {
  title: string;
  subtitle: string;
  forecasts: MarketForecast[];
  open: string | null;
  setOpen: (v: string | null) => void;
  onAsk: (id: string) => Promise<void>;
  busy: string | null;
  msg: Record<string, string>;
  advanced: boolean;
}) {
  if (forecasts.length === 0) return null;
  // Biggest net edge first: that is the only ordering that matters here.
  const sorted = [...forecasts].sort((a, b) => b.netEdgeBps - a.netEdgeBps);

  return (
    <Card title={title} icon={Target} subtitle={subtitle}>
      <div className="space-y-1.5">
        {sorted.map((f) => (
          <div key={f.marketId} className="rounded-lg border border-cyber-border bg-cyber-bg/40">
            <button
              type="button"
              onClick={() => setOpen(open === f.marketId ? null : f.marketId)}
              aria-expanded={open === f.marketId}
              aria-label={`${f.symbol}: the market says ${pct(f.marketP)}, Pythia says ${pct(f.ensembleP)}, ${
                f.action === "hold" ? "not acting" : `would ${f.action}`
              }. Show details.`}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm hover:bg-cyber-surface-2/60 sm:gap-3"
            >
              <ChevronRight
                size={14}
                aria-hidden
                className={`shrink-0 text-cyber-text-faint transition-transform ${open === f.marketId ? "rotate-90" : ""}`}
              />
              <span className="min-w-0 flex-1 truncate">{f.symbol}</span>
              <span className="shrink-0 font-mono text-xs text-cyber-text-faint">
                <span className="hidden sm:inline">{advanced ? "mkt " : "others "}</span>
                {pct(f.marketP)}
              </span>
              <span className="shrink-0 font-mono text-xs" aria-hidden>
                → <span className="font-bold text-accent">{pct(f.ensembleP)}</span>
              </span>
              {advanced && (
                <span
                  className={`hidden w-20 shrink-0 text-right font-mono text-xs sm:inline ${
                    f.netEdgeBps > 0 ? "text-success" : "text-cyber-text-faint"
                  }`}
                >
                  {f.netEdgeBps > 0 ? "+" : ""}
                  {f.netEdgeBps.toFixed(0)}bps
                </span>
              )}
              {/* On a phone only a buy or sell earns the room; "not acting" is the default. */}
              <span className={f.action === "hold" ? "hidden shrink-0 sm:inline" : "shrink-0"}>
                <Badge tone={f.action === "buy" ? "green" : f.action === "sell" ? "red" : "neutral"}>
                  {advanced ? f.action : f.action === "hold" ? "not acting" : `would ${f.action}`}
                </Badge>
              </span>
            </button>

            {open === f.marketId &&
              (advanced ? (
                <Detail f={f} onAsk={onAsk} busy={busy === f.marketId} msg={msg[f.marketId]} />
              ) : (
                <SimpleDetail f={f} onAsk={onAsk} busy={busy === f.marketId} msg={msg[f.marketId]} />
              ))}
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
        <Readout label="Market" value={pct(f.marketP)} />
        <Readout label="Pooled sources" value={pct(f.modelP)} />
        <Readout label="Ensemble" value={pct(f.ensembleP)} tone="cyan" />
        <Readout label="Kelly stake" value={`${(f.kelly * 100).toFixed(2)}%`} />
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
          hint={`${f.effectiveSources.toFixed(1)} of ${f.sources.length}: agreement is not independence`}
        />
      </div>

      <div className="mb-3 rounded-lg border border-cyber-border bg-cyber-bg/40 px-3 py-2 text-xs text-cyber-text-dim">
        <span className="font-mono font-bold uppercase tracking-widest text-cyber-text-faint">Verdict</span>{" "}
        {f.reason}
        <div className="mt-1 font-mono text-[11px] text-cyber-text-faint">
          gross edge {f.edgeBps.toFixed(0)}bps − {f.costBps.toFixed(0)}bps round-trip cost ={" "}
          {f.netEdgeBps.toFixed(0)}bps net <Explain text={explain("bps")!} label="bps" />
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

/**
 * The same forecast, in sentences. No basis points, no Kelly, no log-odds — the
 * three questions a beginner actually has: what does it think, why is it not
 * acting, and who told it that.
 */
function SimpleDetail({
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
  const mine = Math.round(f.ensembleP * 100);
  const mkt = Math.round(f.marketP * 100);
  const diff = mine - mkt;
  const proven = f.sources.filter((s) => s.trust > 0).length;

  return (
    <div className="space-y-3 border-t border-cyber-border px-3 py-3 text-sm">
      <p className="text-cyber-text-dim">
        Everyone trading this market prices it at <b className="text-cyber-text">{mkt}%</b>. Pythia's
        best guess is <b className="text-accent">{mine}%</b>.{" "}
        {Math.abs(diff) < 1
          ? "It agrees with the market."
          : `It thinks that is ${Math.abs(diff)} point${Math.abs(diff) === 1 ? "" : "s"} too ${diff > 0 ? "low" : "high"}.`}
      </p>

      <div className="rounded-lg border border-cyber-border bg-cyber-bg/40 px-3 py-2 text-cyber-text-dim">
        <b className="text-cyber-text">
          {f.action === "hold" ? "It is not acting on this." : `It would ${f.action}.`}
        </b>{" "}
        {plainReason(f.reason)}
      </div>

      {f.sources.length > 0 && (
        <div className="text-cyber-text-dim">
          <div className="mb-1 font-mono text-[11px] uppercase tracking-widest text-cyber-text-faint">
            Who contributed
          </div>
          <ul className="space-y-0.5">
            {f.sources.map((s) => (
              <li key={s.source} className="text-[13px]">
                <span className="text-cyber-text">{friendlySource(s.source)}</span> said{" "}
                <span className="font-mono">{Math.round(s.p * 100)}%</span>,{" "}
                {s.trust > 0 ? (
                  <span className="text-success">has a proven record ({s.n} checked)</span>
                ) : (
                  <span className="text-cyber-text-faint">
                    unproven so far{s.n > 0 ? `, ${s.n} checked` : ""}, so it barely counts
                  </span>
                )}
              </li>
            ))}
          </ul>
          {proven === 0 && (
            <div className="mt-1.5 text-[11px] text-cyber-text-faint">
              None of them has beaten the market yet, so Pythia mostly sticks with the market price.
            </div>
          )}
        </div>
      )}

      {canRunEnsemble() && (
        <div className="flex flex-wrap items-center gap-2">
          <Button tone="purple" icon={Sparkles} disabled={busy} onClick={() => void onAsk(f.marketId)}>
            {busy ? "Asking…" : "Ask the AI models"}
          </Button>
          <span className="text-[11px] text-cyber-text-faint">uses your API credit</span>
          {msg && <span className="text-xs text-cyber-text-dim">{msg}</span>}
        </div>
      )}
    </div>
  );
}

/** `llm:anthropic` → `Claude`, `stat:longshot` → a description of the idea. */
function friendlySource(source: string): string {
  const map: Record<string, string> = {
    "llm:anthropic": "Claude",
    "llm:openai": "GPT",
    "llm:xai": "Grok",
    "llm:zai": "GLM",
    "llm:deepseek": "DeepSeek",
    "llm:google": "Gemini",
    "llm:groq": "Groq",
    "llm:openrouter": "OpenRouter",
    "llm:mistral": "Mistral",
    "llm:ollama": "Your local model",
    "stat:longshot": "The long-shot rule",
    "stat:momentum": "Recent drift",
    "stat:drift": "The trend",
  };
  return map[source] ?? source;
}

/** Translate the engine's reason string out of trading vocabulary. */
function plainReason(reason: string): string {
  if (reason.includes("track record")) {
    return "Nothing has proven itself against the market yet, so it will not bet on its own opinion.";
  }
  if (reason.includes("round-trip cost")) {
    return "The difference is smaller than the fees it would pay to trade it.";
  }
  if (reason.includes("below the")) {
    return "The difference is real but too small to be worth trading.";
  }
  if (reason.includes("no forecaster")) {
    return "Nothing has an opinion on this one.";
  }
  return reason;
}

function SourceRow({ s }: { s: SourceView }) {
  const silenced = s.weight <= 0;
  // Redundancy cut: how much of this source's weight another source was already
  // providing. Only worth showing when it actually bit.
  const redundancy = s.rawWeight > 0 ? 1 - s.weight / s.rawWeight : 0;
  return (
    <div className="rounded-lg border border-cyber-border bg-cyber-bg/30 px-3 py-1.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        <Layers size={11} className="shrink-0 text-cyber-text-faint" />
        <span className="font-mono text-xs">{s.source}</span>
        <span className="font-mono text-xs text-cyber-text-dim">{pct(s.p)}</span>
        {Math.abs(s.p - s.rawP) > 0.005 && (
          <span className="text-[10px] text-cyber-text-faint">(said {pct(s.rawP)}, recalibrated)</span>
        )}
        <span className="flex-1" />
        {redundancy > 0.05 && (
          <span
            className="text-[10px] text-warning"
            title="Its errors look like another source's, so the pool counts it less"
          >
            −{(redundancy * 100).toFixed(0)}% redundant
          </span>
        )}
        <Badge tone={s.trust > 0 ? "green" : silenced ? "red" : "neutral"}>
          {s.trust > 0 ? `trust ${s.trust.toFixed(2)}` : silenced ? "silenced" : "unproven"}
        </Badge>
        <span className="w-16 text-right text-[10px] text-cyber-text-faint">n={s.n}</span>
      </div>
      {/* The shrinkage chain, when it differs from the raw number — otherwise
          "trust 0.31" on 4 samples looks like it came from nowhere. */}
      {s.skill && Math.abs(s.skill.pooled - s.skill.raw) > 0.01 && (
        <div className="mt-0.5 pl-5 text-[10px] text-cyber-text-faint">
          skill {(s.skill.raw * 100).toFixed(0)}% raw on {s.skill.n} →{" "}
          {(s.skill.pooled * 100).toFixed(0)}% pooled (source {(s.skill.source * 100).toFixed(0)}% on{" "}
          {s.skill.nSource}, pool {(s.skill.global * 100).toFixed(0)}%)
        </div>
      )}
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
    <Card
      title="Source scoreboard"
      icon={Gauge}
      subtitle={
        <>
          Brier score against reality, compared with the market's score on <b>the same questions</b>. Positive skill is
          the only thing that earns weight: a confident rationale earns nothing.
        </>
      }
    >
      <div className="-mx-1 overflow-x-auto px-1">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="font-mono text-[10px] uppercase tracking-widest text-cyber-text-faint">
              <th className="py-1 text-left font-normal">Source</th>
              <th className="py-1 text-left font-normal">Question</th>
              <th className="py-1 text-left font-normal">Class</th>
              <th className="py-1 text-right font-normal"><Term k="n">n</Term></th>
              <th className="py-1 text-right font-normal"><Term>Brier</Term></th>
              <th className="py-1 text-right font-normal">Market</th>
              <th className="py-1 text-right font-normal"><Term>Skill</Term></th>
              <th className="py-1 text-right font-normal"><Term>Pooled</Term></th>
              <th className="py-1 text-right font-normal"><Term>Bias</Term></th>
              <th className="py-1 text-right font-normal"><Term>Trust</Term></th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((t) => {
              const bias = t.score.meanForecast - t.score.meanOutcome;
              return (
                <tr key={`${t.source}-${t.kind}-${t.category}`} className="border-t border-cyber-border/50">
                  <td className="py-1 font-mono text-xs">{t.source}</td>
                  <td className="py-1 text-xs text-cyber-text-faint">{t.kind}</td>
                  <td className="py-1 text-xs text-cyber-text-faint">{t.category}</td>
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
                  <td
                    className="py-1 text-right font-mono text-xs text-cyber-text-dim"
                    title="After partial pooling toward this source's overall record and the pool's"
                  >
                    {t.skill ? `${(t.skill.pooled * 100).toFixed(1)}%` : "-"}
                  </td>
                  <td className="py-1 text-right font-mono text-xs text-cyber-text-dim">
                    {bias > 0 ? "+" : ""}
                    {(bias * 100).toFixed(1)}pp
                  </td>
                  <td className="py-1 text-right font-mono text-xs">
                    {t.trust > 0 ? t.trust.toFixed(2) : "-"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-2 text-[11px] leading-snug text-cyber-text-faint">
        <b>Brier</b>: mean squared error against the 0/1 outcome; 0.25 is what always saying 50% scores.{" "}
        <b>Skill</b>: how much better than the market on the same questions. <b>Pooled</b>: that skill
        after partial pooling toward the source's overall record and the pool's, so a thin record on one
        market class is carried by a deep one elsewhere. <b>Bias</b>: systematic over- or
        under-forecasting. <b>Trust</b>: pooled skill discounted by how little evidence there is for it.
      </div>
    </Card>
  );
}

function Gauge2({ label, value, hint }: { label: string; value: number; hint: string }) {
  return (
    <div className="rounded-lg border border-cyber-border bg-cyber-bg/30 px-3 py-2">
      <div className="mb-1 flex items-center justify-between gap-2 text-[10px] font-medium uppercase tracking-wider text-cyber-text-faint">
        <Term k={label}>{label}</Term>
        <span className="font-mono">{(value * 100).toFixed(0)}%</span>
      </div>
      <Meter pct={Math.max(0, Math.min(1, value)) * 100} label={label} />
      <div className="mt-1 text-[11px] text-cyber-text-faint">{hint}</div>
    </div>
  );
}

function pct(p: number): string {
  return `${(p * 100).toFixed(1)}%`;
}
