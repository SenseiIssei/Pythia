import { useState } from "react";
import { ArrowDownRight, ArrowUpRight, Minus, ShieldCheck, Sparkles, Target, TriangleAlert } from "lucide-react";
import { Badge, Button, Field, List, ListRow, Notice, Page, Sheet, Stat, inputCls } from "../design";
import { Explain, KeyStats, Meter, More, Nothing, Section, Term, num, plural, share } from "../pagekit";
import { actionWord, bps, forecastCall, plainReason, predictionSummary, sortByEdge, type Lean } from "../pagekit/picks";
import { explain } from "../glossary";
import { liveMode } from "../live";
import { useStore } from "../store";
import { runEnsemble, canRunEnsemble } from "../predict";
import { useAdvanced } from "../uiMode";
import type { MarketForecast, SourceView, Track } from "../types";

const LEAN_TEXT: Record<Lean, string> = { up: "text-up", down: "text-down", flat: "text-muted" };
const LEAN_ICON = { up: ArrowUpRight, down: ArrowDownRight, flat: Minus } as const;

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
  const sum = predictionSummary(forecasts, forecastStats, tracks);
  const opened = open ? forecasts.find((f) => f.marketId === open) : undefined;

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

  const title = "Predictions";
  const subtitle = advanced
    ? "Ensemble forecasts scored against the market: Polymarket events and price direction."
    : "What Pythia thinks will happen, next to what everyone else thinks, and whether it has earned the right to act on it.";

  const contextCard = canRunEnsemble() ? (
    <Section
      title={advanced ? "Context for the models" : "Something the AI models should know"}
      hint="Optional. Every model gets these notes word for word, so any disagreement between them is about the question, not the wording."
    >
      <Field label="Notes (optional)">
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          placeholder="e.g. CPI print came in at 2.9% this morning; the committee meets on the 18th"
          className={inputCls}
        />
      </Field>
    </Section>
  ) : null;

  // The forecasting layer lives in the Rust core. The browser demo has none, so
  // say that instead of showing an empty page.
  if (liveMode() === "none" && forecasts.length === 0) {
    return (
      <Page title={title} subtitle={subtitle}>
        <Section title="Not available here" hint="Forecasts are made, written down and scored by the engine.">
          <Nothing icon={Target} title="Predictions need the desktop app or a connected server">
            Forecasts are made, written down and scored by the engine in the desktop app or on a backend server. This
            browser version only practises trading with fake money, so there is nothing to show here yet.
          </Nothing>
        </Section>
      </Page>
    );
  }

  return (
    <Page title={title} subtitle={subtitle}>
      <KeyStats
        items={[
          {
            label: "Would act on",
            value: `${sum.acting} of ${plural(sum.total, "market")}`,
            sub: sum.acting === 0 ? "It agrees with the market everywhere, on purpose." : "Where it disagrees with the market by more than the costs.",
            help: "Markets where Pythia's forecast differs from the market price by more than it would cost to trade.",
          },
          {
            label: "Beat the market",
            value: sum.sources > 0 ? `${sum.trusted} of ${sum.sources}` : String(sum.trusted),
            tone: sum.trusted > 0 ? "up" : "plain",
            sub: sum.sources === 1 ? "source, on a checked record" : "sources, on a checked record",
            help: "Sources whose past forecasts were more accurate than the market price on the same questions. Only these may pull Pythia away from the market.",
          },
          {
            label: "Forecasts checked",
            value: sum.checked.toLocaleString("en-US"),
            sub: `${sum.waiting.toLocaleString("en-US")} waiting for the outcome, ${sum.recorded.toLocaleString("en-US")} written down`,
            help: "Forecasts whose outcome is known, so they could be scored against what really happened.",
          },
        ]}
      />

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
            The market price is the default answer, and every source has to <b>earn</b> a deviation from it by beating it
            on a scored track record. Until one does, the ensemble sits on the market price, the edge is about zero, and
            nothing trades. That is the honest state, not a broken one.
          </>
        ) : untrusted ? (
          <>
            The price a market trades at is everyone's combined guess. Pythia only moves away from it once one of its
            sources has beaten that guess on a checked record. Until then it mostly agrees with the market and makes no
            bets, on purpose.
          </>
        ) : (
          <>
            The price a market trades at is everyone's combined guess. Some of Pythia's sources have beaten that guess on
            a checked record, so where they disagree it may lean away from the market, but only as far as they have
            earned.
          </>
        )}
      </Notice>

      {/* Coherence is an arbitrage list. Real, but meaningless without knowing
          what a leg and a basis point are. */}
      {advanced && coherence.length > 0 && (
        <Section
          title="Coherence breaks"
          hint="A market's own outcomes must price to 1. When they do not, the gap is arithmetic, not a forecast: no opinion about the world is involved."
        >
          <List>
            {coherence.map((b) => (
              <div key={b.eventId} className="flex items-start justify-between gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <div className="break-words text-[15px] font-semibold text-ink">{b.title}</div>
                  <div className="tabular text-[13px] text-muted" title="Sum of the outcome prices">
                    Outcomes add up to {num(b.sum, 4)}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <div className={`tabular text-[15px] font-semibold ${b.netBps > 0 ? "text-up" : "text-muted"}`}>
                    <Term k="bps">{bps(b.netBps)}</Term>
                  </div>
                  <div className="mt-0.5">
                    <Badge tone={b.actionable ? "good" : "neutral"}>{b.actionable ? "Actionable" : b.kind === "overpriced" ? "Needs shorting" : "Below costs"}</Badge>
                  </div>
                </div>
              </div>
            ))}
          </List>
        </Section>
      )}

      {advanced && contextCard}

      {events.length === 0 && prices.length === 0 && (
        <Section title="Forecasts" hint="Each market Pythia watches gets a forecast here.">
          <Nothing icon={Target} title="No forecasts yet">
            Prediction markets usually arrive within a few seconds of starting. If this stays empty, check that the engine
            is running on the Home page.
          </Nothing>
        </Section>
      )}

      <ForecastList
        title={advanced ? "Event markets" : "Will this happen?"}
        hint={
          advanced
            ? "P(YES): the question a model can actually reason about. Biggest net edge first."
            : "How likely each thing is according to Pythia, next to what everyone else thinks. Tap a row for the reasons."
        }
        forecasts={events}
        onOpen={setOpen}
        advanced={advanced}
      />
      <ForecastList
        title={advanced ? "Directional markets" : "Will this go up?"}
        hint={
          advanced
            ? "P(price higher over the forecast horizon). Resolves on a timer, which is where the calibration data comes from."
            : "Chance the price is higher a while from now. 50% means it has no idea, which is usually the honest answer."
        }
        forecasts={prices}
        onOpen={setOpen}
        advanced={advanced}
      />

      {/* The scoreboard is the most important thing on this page and the least
          readable without the vocabulary. Advanced only. */}
      {advanced && tracks.length > 0 && <Scoreboard tracks={tracks} />}

      {/* A beginner reads the forecasts first; the optional notes come after. */}
      {!advanced && contextCard}

      <Sheet open={!!opened} onClose={() => setOpen(null)} title={opened?.symbol ?? "Forecast"} wide>
        {opened &&
          (advanced ? (
            <Detail f={opened} onAsk={ask} busy={busy === opened.marketId} msg={msg[opened.marketId]} />
          ) : (
            <SimpleDetail f={opened} onAsk={ask} busy={busy === opened.marketId} msg={msg[opened.marketId]} />
          ))}
      </Sheet>
    </Page>
  );
}

function ForecastList({
  title,
  hint,
  forecasts,
  onOpen,
  advanced,
}: {
  title: string;
  hint: string;
  forecasts: MarketForecast[];
  onOpen: (id: string) => void;
  advanced: boolean;
}) {
  if (forecasts.length === 0) return null;
  // Biggest net edge first: that is the only ordering that matters here.
  const sorted = sortByEdge(forecasts);
  return (
    <Section title={title} hint={hint}>
      <List>
        {sorted.map((f) => {
          const c = forecastCall(f);
          const a = actionWord(f.action);
          const Icon = LEAN_ICON[c.lean];
          return (
            <ListRow
              key={f.marketId}
              onClick={() => onOpen(f.marketId)}
              title={<span className="block whitespace-normal break-words">{f.symbol}</span>}
              subtitle={
                <span className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                  <span className={`inline-flex items-center gap-0.5 font-semibold ${LEAN_TEXT[c.lean]}`}>
                    <Icon size={14} aria-hidden className="shrink-0" />
                    {c.call}
                  </span>
                  <span className="tabular">· {advanced ? "market" : "others say"} {share(f.marketP)}</span>
                  {advanced && <span className="tabular">· {bps(f.netEdgeBps)} net</span>}
                  {f.action !== "hold" && <Badge tone={a.tone}>{a.label}</Badge>}
                </span>
              }
              right={c.chance}
              rightSub={<span className="text-muted">{c.of}</span>}
              chevron
            />
          );
        })}
      </List>
    </Section>
  );
}

function AskButton({ f, onAsk, busy, msg, advanced }: { f: MarketForecast; onAsk: (id: string) => Promise<void>; busy: boolean; msg?: string; advanced: boolean }) {
  if (!canRunEnsemble()) return null;
  return (
    <div className="mt-4 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" icon={Sparkles} disabled={busy} onClick={() => void onAsk(f.marketId)}>
          {busy ? (advanced ? "Asking models" : "Asking") : advanced ? "Ask the model ensemble" : "Ask the AI models"}
        </Button>
        <span className="text-[13px] text-faint">{advanced ? "One API call per configured provider" : "Uses your API credit"}</span>
      </div>
      {msg && (
        <p role="status" className="break-words text-[13px] text-muted">
          {msg}
        </p>
      )}
    </div>
  );
}

function Detail({ f, onAsk, busy, msg }: { f: MarketForecast; onAsk: (id: string) => Promise<void>; busy: boolean; msg?: string }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label={<Term k="Market">Market</Term>} value={share(f.marketP, 1)} />
        <Stat label={<Term k="Pooled sources">Pooled sources</Term>} value={share(f.modelP, 1)} />
        <Stat label={<Term k="Ensemble">Ensemble</Term>} value={<span className="text-accent">{share(f.ensembleP, 1)}</span>} />
        <Stat label={<Term k="Kelly stake">Kelly stake</Term>} value={share(f.kelly, 2)} />
      </div>

      <div className="divide-y divide-line">
        <Gauge label="Trust in the pool" value={f.trust} hint="How far it may pull from the market." />
        <Gauge label="Disagreement" value={Math.min(f.disagreement / 3, 1)} hint={`${num(f.disagreement)} in log-odds`} />
        <Gauge
          label="Effective sources"
          value={Math.min(f.effectiveSources / 5, 1)}
          hint={`${num(f.effectiveSources, 1)} of ${f.sources.length}: agreement is not independence`}
        />
      </div>

      <div className="rounded-control bg-surface-2 px-4 py-3 text-sm text-muted">
        <span className="font-semibold text-ink">Verdict:</span> {f.reason}
        <div className="tabular mt-1 flex flex-wrap items-center gap-1 text-[13px]">
          Gross edge {bps(f.edgeBps)}, minus {Math.round(f.costBps)} bps round-trip cost, leaves {bps(f.netEdgeBps)} net
          <Explain text={explain("bps")!} label="bps" />
        </div>
      </div>

      <div>
        <h3 className="text-[15px] font-semibold text-ink">Sources</h3>
        {f.sources.length > 0 ? (
          <List>
            {f.sources.map((s) => (
              <SourceRow key={s.source} s={s} />
            ))}
          </List>
        ) : (
          <p className="py-2 text-[13px] text-muted">No source produced an opinion for this market.</p>
        )}
      </div>

      <AskButton f={f} onAsk={onAsk} busy={busy} msg={msg} advanced />
    </div>
  );
}

/**
 * The same forecast, in sentences. No basis points, no Kelly, no log-odds: the
 * three questions a beginner actually has: what does it think, why is it not
 * acting, and who told it that.
 */
function SimpleDetail({ f, onAsk, busy, msg }: { f: MarketForecast; onAsk: (id: string) => Promise<void>; busy: boolean; msg?: string }) {
  const mine = Math.round(f.ensembleP * 100);
  const mkt = Math.round(f.marketP * 100);
  const diff = mine - mkt;
  const proven = f.sources.filter((s) => s.trust > 0).length;
  const c = forecastCall(f);

  return (
    <div className="space-y-4 text-[15px]">
      <div className="grid grid-cols-2 gap-4">
        <Stat label="Everyone else" value={`${mkt}%`} />
        <Stat label="Pythia" value={<span className="text-accent">{`${mine}%`}</span>} sub={<span className={LEAN_TEXT[c.lean]}>{c.call}</span>} />
      </div>
      <p className="text-muted">
        Everyone trading this market prices it at <b className="text-ink">{mkt}%</b>. Pythia's best guess is{" "}
        <b className="text-ink">{mine}%</b>.{" "}
        {Math.abs(diff) < 1 ? "It agrees with the market." : `It thinks that is ${Math.abs(diff)} point${Math.abs(diff) === 1 ? "" : "s"} too ${diff > 0 ? "low" : "high"}.`}
      </p>

      <div className="rounded-control bg-surface-2 px-4 py-3 text-muted">
        <b className="text-ink">{f.action === "hold" ? "It is not acting on this." : `It would ${f.action}.`}</b> {plainReason(f.reason)}
      </div>

      {f.sources.length > 0 && (
        <div>
          <h3 className="text-[15px] font-semibold text-ink">Who contributed</h3>
          <List>
            {f.sources.map((s) => (
              <div key={s.source} className="flex items-start justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <div className="text-[15px] text-ink">{friendlySource(s.source)}</div>
                  <div className={`text-[13px] ${s.trust > 0 ? "text-up" : "text-muted"}`}>
                    {s.trust > 0 ? `Has a proven record (${s.n} checked)` : `Unproven so far${s.n > 0 ? `, ${s.n} checked` : ""}, so it barely counts`}
                  </div>
                </div>
                <div className="tabular shrink-0 text-[15px] font-semibold text-ink">{Math.round(s.p * 100)}%</div>
              </div>
            ))}
          </List>
          {proven === 0 && <p className="mt-1.5 text-[13px] text-muted">None of them has beaten the market yet, so Pythia mostly sticks with the market price.</p>}
        </div>
      )}

      <AskButton f={f} onAsk={onAsk} busy={busy} msg={msg} advanced={false} />
    </div>
  );
}

/** `llm:openai` to `GPT`, `stat:longshot` to a description of the idea. */
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

function SourceRow({ s }: { s: SourceView }) {
  const silenced = s.weight <= 0;
  // Redundancy cut: how much of this source's weight another source was already
  // providing. Only worth showing when it actually bit.
  const redundancy = s.rawWeight > 0 ? 1 - s.weight / s.rawWeight : 0;
  return (
    <div className="py-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="break-all text-[15px] font-semibold text-ink">{s.source}</div>
          <div className="tabular text-[13px] text-muted">
            {Math.abs(s.p - s.rawP) > 0.005 ? `Said ${share(s.rawP, 1)}, recalibrated` : "As said"} · n={s.n}
            {redundancy > 0.05 && (
              <span className="text-warn" title="Its errors look like another source's, so the pool counts it less">
                {" "}
                · −{Math.round(redundancy * 100)}% redundant
              </span>
            )}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="tabular text-[15px] font-semibold text-ink">{share(s.p, 1)}</div>
          <Badge tone={s.trust > 0 ? "good" : silenced ? "bad" : "neutral"}>{s.trust > 0 ? `Trust ${num(s.trust)}` : silenced ? "Silenced" : "Unproven"}</Badge>
        </div>
      </div>
      {/* The shrinkage chain, when it differs from the raw number: otherwise
          "trust 0.31" on 4 samples looks like it came from nowhere. */}
      {s.skill && Math.abs(s.skill.pooled - s.skill.raw) > 0.01 && (
        <p className="tabular mt-1 text-[13px] text-muted">
          Skill {share(s.skill.raw)} raw on {s.skill.n}, {share(s.skill.pooled)} pooled (source {share(s.skill.source)} on {s.skill.nSource}, pool{" "}
          {share(s.skill.global)})
        </p>
      )}
      {s.rationale && <p className="mt-1 break-words text-[13px] leading-snug text-muted">{s.rationale}</p>}
    </div>
  );
}

/** The scoreboard that decides everything else on this page. */
function Scoreboard({ tracks }: { tracks: Track[] }) {
  const sorted = [...tracks].sort((a, b) => b.brierSkill - a.brierSkill);
  const th = "py-2 font-medium";
  return (
    <Section
      title="Source scoreboard"
      hint={
        <>
          Accuracy against reality, compared with the market's on <b>the same questions</b>. Only positive skill earns
          weight: a confident explanation earns nothing.
        </>
      }
    >
      <div className="-mx-1 overflow-x-auto px-1">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="text-[13px] text-muted">
              <th className={`${th} text-left`}>Source</th>
              <th className={`${th} text-left`}>Question</th>
              <th className={`${th} text-left`}>Class</th>
              <th className={`${th} text-right`}>
                <Term k="n">n</Term>
              </th>
              <th className={`${th} text-right`}>
                <Term>Brier</Term>
              </th>
              <th className={`${th} text-right`}>Market</th>
              <th className={`${th} text-right`}>
                <Term>Skill</Term>
              </th>
              <th className={`${th} text-right`}>
                <Term>Pooled</Term>
              </th>
              <th className={`${th} text-right`}>
                <Term>Bias</Term>
              </th>
              <th className={`${th} text-right`}>
                <Term>Trust</Term>
              </th>
            </tr>
          </thead>
          <tbody className="tabular">
            {sorted.map((t) => {
              const bias = t.score.meanForecast - t.score.meanOutcome;
              return (
                <tr key={`${t.source}-${t.kind}-${t.category}`} className="border-t border-line">
                  <td className="py-2 font-semibold text-ink">{t.source}</td>
                  <td className="py-2 text-muted">{t.kind}</td>
                  <td className="py-2 text-muted">{t.category}</td>
                  <td className="py-2 text-right">{t.score.n}</td>
                  <td className="py-2 text-right">{num(t.score.brier, 4)}</td>
                  <td className="py-2 text-right text-muted">{num(t.marketScore.brier, 4)}</td>
                  <td className={`py-2 text-right font-semibold ${t.brierSkill > 0 ? "text-up" : "text-down"}`}>
                    {t.brierSkill > 0 ? "+" : ""}
                    {num(t.brierSkill * 100, 1)}%
                  </td>
                  <td className="py-2 text-right text-muted" title="After partial pooling toward this source's overall record and the pool's">
                    {t.skill ? share(t.skill.pooled, 1) : "-"}
                  </td>
                  <td className="py-2 text-right text-muted">
                    {bias > 0 ? "+" : ""}
                    {num(bias * 100, 1)}pp
                  </td>
                  <td className="py-2 text-right">{t.trust > 0 ? num(t.trust) : "-"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-3">
        <More title="What the columns mean">
          <p className="text-[13px] leading-relaxed text-muted">
            <b className="text-ink">Brier</b>: mean squared error against the 0/1 outcome; 0.25 is what always saying 50%
            scores. <b className="text-ink">Skill</b>: how much better than the market on the same questions.{" "}
            <b className="text-ink">Pooled</b>: that skill after partial pooling toward the source's overall record and
            the pool's, so a thin record on one market class is carried by a deep one elsewhere.{" "}
            <b className="text-ink">Bias</b>: systematic over- or under-forecasting. <b className="text-ink">Trust</b>:
            pooled skill discounted by how little evidence there is for it.
          </p>
        </More>
      </div>
    </Section>
  );
}

function Gauge({ label, value, hint }: { label: string; value: number; hint: string }) {
  const v = Math.max(0, Math.min(1, value));
  return (
    <div className="py-3">
      <div className="mb-1.5 flex items-center justify-between gap-2 text-[15px] text-ink">
        <Term k={label}>{label}</Term>
        <span className="tabular font-semibold">{share(v)}</span>
      </div>
      <Meter pct={v * 100} label={label} />
      <div className="mt-1 text-[13px] text-muted">{hint}</div>
    </div>
  );
}
