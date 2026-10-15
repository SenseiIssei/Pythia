import { useEffect, useMemo, useState } from "react";
import { ArrowDownRight, ArrowUpRight, BrainCircuit, Minus, Sparkles, TriangleAlert } from "lucide-react";
import { Badge, Button, Field, List, ListRow, Notice, Page, Stat, inputCls } from "../design";
import { KeyStats, Meter, More, Nothing, Row, Section, SwitchRow, share } from "../pagekit";
import { ageText, directionWord, recentViews, strengthWord, viewCounts, type Lean } from "../pagekit/picks";
import { useStore } from "../store";
import { aiMode, aiProviders, aiSignal } from "../ai";
import { setAiPolicy } from "../live";
import type { LlmProviderInfo, LlmSignal, Market } from "../types";

// Build a compact, model-friendly description of one market from live state.
function contextFor(m: Market, hist: number[]): string {
  const recent = hist.slice(-12);
  const lines: string[] = [];
  if (m.kind === "prediction") {
    lines.push(`Prediction market: "${m.symbol}"`);
    lines.push(`Current implied YES probability: ${(m.price * 100).toFixed(1)}%`);
    if (m.modelProb != null) lines.push(`Our EWMA fair-value estimate: ${(m.modelProb * 100).toFixed(1)}%`);
    lines.push(`Estimate the TRUE probability of YES. direction=long if YES is underpriced, short if overpriced.`);
  } else {
    lines.push(`${m.kind === "crypto" ? "Crypto" : "Equity"} market: ${m.symbol}`);
    lines.push(`Last price: ${m.price}`);
    lines.push(`24h change: ${(m.change24h * 100).toFixed(2)}%`);
    lines.push(`Estimate P(price higher over the next ~day). direction=long if you expect up, short if down.`);
  }
  if (m.regime) lines.push(`Regime: ${m.regime} (trend strength ${((m.trendStrength ?? 0) * 100).toFixed(0)}%)`);
  if (recent.length > 2) lines.push(`Recent closes (oldest→newest): ${recent.map((x) => x.toFixed(4)).join(", ")}`);
  return lines.join("\n");
}

const LEAN_TEXT: Record<Lean, string> = { up: "text-up", down: "text-down", flat: "text-muted" };
const LEAN_ICON = { up: ArrowUpRight, down: ArrowDownRight, flat: Minus } as const;

/** An arrow and a word, so the direction never relies on colour alone. */
function Direction({ d, big }: { d: LlmSignal["direction"]; big?: boolean }) {
  const { word, lean } = directionWord(d);
  const Icon = LEAN_ICON[lean];
  return (
    <span className={`inline-flex items-center gap-1 font-semibold ${LEAN_TEXT[lean]} ${big ? "text-2xl" : ""}`}>
      <Icon size={big ? 22 : 16} aria-hidden className="shrink-0" />
      {word}
    </span>
  );
}

/**
 * The always-on overlay, as opposed to the one-off "ask a model" panel below.
 *
 * The bounded authority is the whole design. An LLM cannot be walk-forward
 * validated, its behaviour shifts between model versions, and it will answer
 * confidently about a market it has no edge on, so it is wired as a multiplier
 * on trades the rules already produced, never as a trigger. Worst case it
 * shrinks a good trade; it cannot invent a bad one.
 */
function AiOverlayPanel({ now }: { now: number }) {
  const { aiPolicy, aiViews, aiSpend, markets } = useStore();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function toggle(on: boolean) {
    setBusy(true);
    setErr("");
    try {
      await setAiPolicy({ enabled: on });
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    }
    setBusy(false);
  }

  const symbolOf = (id: string) => markets.find((m) => m.id === id)?.symbol ?? id;
  const recent = recentViews(aiViews, now, aiPolicy.ttlSec);

  return (
    <>
      <Section
        title="Live AI overlay"
        hint="A second opinion on trades your strategies already chose. It can make a trade smaller or stop it, but never start one."
        right={<Badge tone={aiPolicy.enabled ? "good" : "neutral"}>{aiPolicy.enabled ? "On" : "Off"}</Badge>}
      >
        <SwitchRow
          label="Ask a model in the background"
          hint={
            <>
              It attaches a view to each of your markets. A view can shrink or block a trade a strategy already decided to
              make, or raise its size by at most <span className="tabular font-semibold text-ink">{aiPolicy.maxBoost.toFixed(2)}×</span>.
              It can never open a trade on its own, and it never touches exits.
            </>
          }
          on={aiPolicy.enabled}
          disabled={busy}
          onChange={(v) => void toggle(v)}
        />
        {err && (
          <Notice tone="danger" title="The overlay did not switch">
            {err}
          </Notice>
        )}
        <div className="mt-2">
          <More title="Usage and how long views count">
            <List>
              <Row label="Calls" value={aiSpend.calls.toLocaleString("en-US")} help="Requests sent to the model so far." />
              <Row label="Input tokens" value={aiSpend.inputTokens.toLocaleString("en-US")} help="Text sent to the model. Providers bill per token." />
              <Row label="Output tokens" value={aiSpend.outputTokens.toLocaleString("en-US")} help="Text the model wrote back. Usually the pricier kind." />
              <Row label="Errors" value={aiSpend.errors.toLocaleString("en-US")} tone={aiSpend.errors > 0 ? "warn" : "plain"} help="Calls that failed or came back unreadable." />
            </List>
            <p className="mt-2 text-[13px] leading-snug text-muted">
              Views older than {aiPolicy.ttlSec}s are ignored entirely. Every call, veto and size change is written to the
              Journal, so any trade the overlay influenced can be reconstructed afterwards.
            </p>
          </More>
        </div>
      </Section>

      <Section title="Current signals" hint="What the model thinks about each market right now, newest first. Strength is how sure it said it is.">
        {recent.length === 0 ? (
          <Nothing icon={BrainCircuit} title="No signals yet">
            {aiPolicy.enabled ? "The first views arrive as the overlay works through your markets." : "Switch the overlay on above, or ask a model about one market below."}
          </Nothing>
        ) : (
          <List>
            {recent.map(({ view: v, ageSec, stale }) => (
              <div key={v.marketId} className={stale ? "opacity-60" : ""}>
                <ListRow
                  title={<span className="break-all">{symbolOf(v.marketId)}</span>}
                  subtitle={
                    <>
                      <span className="line-clamp-2" title={v.rationale}>
                        {v.rationale}
                      </span>
                      <span className="tabular block text-faint">
                        {stale ? "Expired, no longer counts" : ageText(ageSec)} · answered in {v.latencyMs} ms
                      </span>
                    </>
                  }
                  right={<Direction d={v.direction} />}
                  rightSub={
                    <span className="tabular text-muted" title="How sure the model said it is">
                      {strengthWord(v.confidence)}, {share(v.confidence)}
                    </span>
                  }
                />
              </div>
            ))}
          </List>
        )}
      </Section>
    </>
  );
}

export function Signals() {
  const { markets, history, aiViews, aiPolicy, aiSpend } = useStore();
  const mode = aiMode();
  const [providers, setProviders] = useState<LlmProviderInfo[]>([]);
  const [providerId, setProviderId] = useState("");
  const [model, setModel] = useState("");
  const [marketId, setMarketId] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<LlmSignal | null>(null);
  const now = Date.now();

  useEffect(() => {
    if (mode === "none") return;
    aiProviders()
      .then((ps) => {
        setProviders(ps);
        const first = ps.find((p) => p.configured) ?? ps[0];
        if (first) {
          setProviderId(first.id);
          setModel(first.defaultModel);
        }
      })
      .catch((e) => setErr(String(e)));
  }, [mode]);

  const provider = useMemo(() => providers.find((p) => p.id === providerId), [providers, providerId]);
  const configuredCount = providers.filter((p) => p.configured).length;
  const market = useMemo(() => markets.find((m) => m.id === marketId), [markets, marketId]);

  useEffect(() => {
    if (!marketId && markets.length) setMarketId(markets[0].id);
  }, [markets, marketId]);

  function pickProvider(id: string) {
    setProviderId(id);
    const p = providers.find((x) => x.id === id);
    if (p) setModel(p.defaultModel);
    setResult(null);
    setErr("");
  }

  async function ask() {
    if (!market || !provider) return;
    setBusy(true);
    setErr("");
    setResult(null);
    try {
      const ctx = contextFor(market, history[market.id] ?? []);
      const sig = await aiSignal(provider.id, model.trim(), ctx);
      setResult(sig);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    }
    setBusy(false);
  }

  const subtitle = "Ask an AI model to reason about a market. Advice only: it never places an order by itself.";

  if (mode === "none") {
    return (
      <Page title="AI Signals" subtitle={subtitle}>
        <Section title="Not available here" hint="Model calls need a safe place for your API key.">
          <Nothing icon={TriangleAlert} title="AI signals need the desktop app or a connected server">
            They call model APIs, which needs a safe place for your key and a route the browser is not allowed to take. Use
            the desktop app (keys in the OS keychain) or point a web build at a backend server (
            <code className="font-code text-ink">VITE_PYTHIA_SERVER</code>, keys in its environment).
          </Nothing>
        </Section>
      </Page>
    );
  }

  const counts = viewCounts(aiViews, now, aiPolicy.ttlSec);

  return (
    <Page title="AI Signals" subtitle={`${subtitle} Bring your own API key from any supported provider.`}>
      <KeyStats
        items={[
          {
            label: "Fresh signals",
            value: counts.fresh.toLocaleString("en-US"),
            sub: counts.fresh > 0 ? `${counts.up} up, ${counts.down} down, ${counts.fresh - counts.up - counts.down} no view` : aiPolicy.enabled ? "None fresh yet" : "The overlay is off",
            help: `Model views young enough to count: newer than ${aiPolicy.ttlSec} seconds.`,
          },
          { label: "Calls", value: aiSpend.calls.toLocaleString("en-US"), sub: `${(aiSpend.inputTokens + aiSpend.outputTokens).toLocaleString("en-US")} tokens used` },
          { label: "Errors", value: aiSpend.errors.toLocaleString("en-US"), tone: aiSpend.errors > 0 ? "warn" : "plain" },
        ]}
      />

      <AiOverlayPanel now={now} />

      <Section
        title="Ask a model"
        hint="Pick a provider, a model and a market. You get its view with the reasons, and nothing is traded."
        right={<Badge tone={configuredCount ? "good" : "neutral"}>{configuredCount ? `${configuredCount} configured` : "No keys yet"}</Badge>}
      >
        {configuredCount === 0 && (
          <Notice tone="warning" title="No provider has a key yet" className="mb-4">
            {mode === "native" ? (
              <>Add one in Settings, under AI providers.</>
            ) : (
              <>
                Set a key in the server's environment (e.g. <code className="font-code text-ink">ANTHROPIC_API_KEY</code>).
              </>
            )}{" "}
            You can still try a request: it will tell you what is missing.
          </Notice>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Field label="Provider">
            <select value={providerId} onChange={(e) => pickProvider(e.target.value)} className={inputCls}>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                  {p.configured ? " ✓" : ""}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Model">
            <input
              value={model}
              list="model-suggestions"
              onChange={(e) => setModel(e.target.value)}
              placeholder={provider?.defaultModel ?? "model id"}
              className={inputCls}
            />
            <datalist id="model-suggestions">
              {(provider?.suggestedModels ?? []).map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </Field>

          <Field label="Market">
            <select value={marketId} onChange={(e) => setMarketId(e.target.value)} className={inputCls}>
              {markets.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.symbol} ({m.kind})
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button variant="primary" icon={Sparkles} disabled={busy || !market} onClick={ask}>
            {busy ? "Thinking" : "Ask the model"}
          </Button>
          {provider && !provider.configured && (
            <span className="flex items-center gap-1 text-[13px] text-warn">
              <TriangleAlert size={14} aria-hidden /> {provider.label} has no key yet
            </span>
          )}
        </div>
        {err && (
          <Notice tone="danger" title="The model did not answer" className="mt-4">
            <span className="break-words">{err}</span>
          </Notice>
        )}
      </Section>

      {result && market && (
        <Section title="Answer" hint="One model's opinion, not a trade instruction or financial advice.">
          <div className="mb-4 flex flex-wrap items-center gap-2 text-[13px]">
            <Badge tone="accent">{result.provider}</Badge>
            <span className="break-all text-muted">{result.model}</span>
            <span className="text-faint" aria-hidden>
              ·
            </span>
            <span className="break-all font-semibold text-ink">{market.symbol}</span>
          </div>

          <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
            <Stat label="Direction" value={<Direction d={result.direction} big />} />
            <div className="min-w-0 space-y-1.5">
              <Stat label={market.kind === "prediction" ? "Chance of yes" : "Chance it rises"} value={share(result.probability, 1)} />
              <Meter pct={result.probability * 100} label={market.kind === "prediction" ? "Chance of yes" : "Chance it rises"} />
            </div>
            <div className="min-w-0 space-y-1.5">
              <Stat label="Confidence" value={share(result.confidence)} sub={<span className="text-muted">{strengthWord(result.confidence)}</span>} />
              <Meter pct={result.confidence * 100} label="Confidence" />
            </div>
          </div>

          <p className="mt-5 whitespace-pre-line break-words rounded-control bg-surface-2 px-4 py-3 text-[15px] leading-relaxed text-ink">{result.rationale}</p>

          <p className="mt-3 text-[13px] leading-snug text-muted">
            An advisory opinion, not a trade instruction or financial advice. Models don't reliably predict prices; treat
            this as one input. Nothing here places an order.
          </p>
        </Section>
      )}
    </Page>
  );
}
