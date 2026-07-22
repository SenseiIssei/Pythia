import { useEffect, useMemo, useState } from "react";
import { BrainCircuit, Sparkles, TriangleAlert, ArrowUp, ArrowDown, Minus } from "lucide-react";
import { Card, PageHeader, Badge, Button, Meter, fmtPct } from "../components/ui";
import { useStore } from "../store";
import { aiMode, aiProviders, aiSignal } from "../ai";
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

function DirIcon({ d }: { d: LlmSignal["direction"] }) {
  if (d === "long") return <ArrowUp size={14} className="text-success" />;
  if (d === "short") return <ArrowDown size={14} className="text-danger" />;
  return <Minus size={14} className="text-cyber-text-dim" />;
}

export function Signals() {
  const { markets, history } = useStore();
  const mode = aiMode();
  const [providers, setProviders] = useState<LlmProviderInfo[]>([]);
  const [providerId, setProviderId] = useState("");
  const [model, setModel] = useState("");
  const [marketId, setMarketId] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<LlmSignal | null>(null);

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

  if (mode === "none") {
    return (
      <div className="animate-fade-in max-w-3xl">
        <PageHeader title="AI Signals" subtitle="Ask any LLM to reason about a market" />
        <Card className="border-warning/30 bg-warning/5">
          <div className="flex items-start gap-3">
            <TriangleAlert size={18} className="mt-0.5 shrink-0 text-warning" />
            <div className="text-sm text-cyber-text-dim">
              <div className="font-bold text-warning">Not available in the browser paper build</div>
              AI signals call external model APIs, which needs a key store and a non-CORS path. Run the{" "}
              <span className="text-accent">desktop app</span> (keys in the OS keychain) or point a web build at
              the <span className="text-accent">backend server</span> (<code className="text-accent">VITE_PYTHIA_SERVER</code>,
              keys in its environment).
            </div>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="animate-fade-in max-w-4xl">
      <PageHeader
        title="AI Signals"
        subtitle="Bring any API key — Claude, GPT, Grok, GLM, Gemini, DeepSeek & more reason over your markets"
      />

      <Card
        className="mb-4"
        title="Ask a model"
        right={
          <Badge tone={configuredCount ? "green" : "neutral"}>
            {configuredCount ? `${configuredCount} configured` : "no keys yet"}
          </Badge>
        }
      >
        {configuredCount === 0 && (
          <div className="mb-3 rounded border border-warning/30 bg-warning/5 px-3 py-2 text-xs text-cyber-text-dim">
            No provider has a key yet.{" "}
            {mode === "native" ? (
              <>Add one in <span className="text-accent">Settings → AI providers</span>.</>
            ) : (
              <>Set a key in the server's environment (e.g. <code className="text-accent">ANTHROPIC_API_KEY</code>).</>
            )}{" "}
            You can still try a request — it will tell you what's missing.
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field label="Provider">
            <select value={providerId} onChange={(e) => pickProvider(e.target.value)} className={selCls}>
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
              className={selCls}
            />
            <datalist id="model-suggestions">
              {(provider?.suggestedModels ?? []).map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </Field>

          <Field label="Market">
            <select value={marketId} onChange={(e) => setMarketId(e.target.value)} className={selCls}>
              {markets.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.symbol} ({m.kind})
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div className="mt-3 flex items-center gap-3">
          <Button tone="purple" icon={Sparkles} disabled={busy || !market} onClick={ask}>
            {busy ? "Thinking…" : "Ask the model"}
          </Button>
          {provider && !provider.configured && (
            <span className="text-xs text-warning">⚠ {provider.label} has no key configured</span>
          )}
          {err && <span className="text-xs text-danger">{err}</span>}
        </div>
      </Card>

      {result && market && (
        <Card title="Signal" right={<BrainCircuit size={15} className="text-purple-neon" />}>
          <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
            <Badge tone="purple">{result.provider}</Badge>
            <span className="text-cyber-text-faint">{result.model}</span>
            <span className="text-cyber-text-faint">·</span>
            <span className="text-cyber-text-dim">{market.symbol}</span>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <div className="mb-1 text-[11px] uppercase tracking-widest text-cyber-text-faint">Direction</div>
              <div className="flex items-center gap-1.5 text-lg font-bold">
                <DirIcon d={result.direction} />
                <span
                  className={
                    result.direction === "long"
                      ? "text-success"
                      : result.direction === "short"
                        ? "text-danger"
                        : "text-cyber-text-dim"
                  }
                >
                  {result.direction.toUpperCase()}
                </span>
              </div>
            </div>
            <div>
              <div className="mb-1 text-[11px] uppercase tracking-widest text-cyber-text-faint">
                {market.kind === "prediction" ? "P(YES)" : "P(up)"}
              </div>
              <div className="text-lg font-bold text-accent">{fmtPct(result.probability, 1)}</div>
              <Meter pct={result.probability * 100} tone="cyan" />
            </div>
            <div>
              <div className="mb-1 text-[11px] uppercase tracking-widest text-cyber-text-faint">Confidence</div>
              <div className="text-lg font-bold text-purple-neon">{fmtPct(result.confidence, 0)}</div>
              <Meter pct={result.confidence * 100} tone="purple" />
            </div>
          </div>

          <div className="mt-4 rounded-lg border border-cyber-border bg-cyber-surface/50 p-3 text-sm text-cyber-text-dim">
            {result.rationale}
          </div>

          <div className="mt-3 text-[11px] leading-snug text-cyber-text-faint">
            An advisory opinion, not a trade instruction or financial advice. Models don't reliably predict prices;
            treat this as one input. Nothing here places an order.
          </div>
        </Card>
      )}
    </div>
  );
}

const selCls =
  "w-full rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-xs text-cyber-text-dim">{label}</label>
      {children}
    </div>
  );
}
