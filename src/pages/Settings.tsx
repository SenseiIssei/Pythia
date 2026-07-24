import { useEffect, useState, type ReactNode } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  KeyRound,
  Lock,
  Link2,
  ShieldCheck,
  Trash2,
  Bell,
  Send,
  BrainCircuit,
  PlugZap,
  SlidersHorizontal,
  TriangleAlert,
} from "lucide-react";
import { Card, PageHeader, Badge, Button } from "../components/ui";
import { isTauri } from "../engine";
import { aiMode, aiProviders, saveAiKey, clearAiKey } from "../ai";
import { alpacaAccount } from "../live";
import { DEFAULT_PREFS, EFFORTS, TIMEFRAMES, getPrefs, savePrefs, testLlmKey, type Prefs } from "../prefs";
import type { LlmProviderInfo } from "../types";

interface VenueCfg {
  id: string;
  name: string;
  fields: { key: string; label: string; secret?: boolean }[];
  note: string;
}

const VENUES: VenueCfg[] = [
  {
    id: "polymarket",
    name: "Polymarket",
    fields: [
      { key: "pk", label: "Polygon private key", secret: true },
      { key: "funder", label: "Funder / proxy address" },
    ],
    note: "⚠ Geoblocked for US persons. You are responsible for legal use where you live. See SAFETY.md.",
  },
  {
    id: "crypto",
    name: "Crypto exchange (Kraken)",
    fields: [
      { key: "key", label: "API key" },
      { key: "secret", label: "API secret", secret: true },
    ],
    note: "Spot only in v1. Grant the key trade permission but NOT withdrawal.",
  },
  {
    id: "alpaca",
    name: "Alpaca — Paper",
    fields: [
      { key: "keyId", label: "API key id" },
      { key: "secret", label: "API secret", secret: true },
    ],
    note: "Keys from the Paper Trading account (paper-api.alpaca.markets). Real API, real order lifecycle, fake money.",
  },
  {
    id: "alpaca-live",
    name: "Alpaca — Live 💵",
    fields: [
      { key: "keyId", label: "API key id" },
      { key: "secret", label: "API secret", secret: true },
    ],
    note: "⚠ REAL MONEY. Keys from the Live account — a different pair to the paper ones. Storing them changes nothing on its own: routing still needs a typed ARM LIVE on the Live page.",
  },
];

export function Settings() {
  const native = isTauri();
  const [status, setStatus] = useState<Record<string, boolean>>({});

  async function refresh() {
    if (!native) return;
    try {
      const rows = await invoke<[string, boolean][]>("venue_status");
      setStatus(Object.fromEntries(rows));
    } catch {
      /* daemon not ready */
    }
  }
  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="animate-fade-in">
      <PageHeader title="Settings" subtitle="Venue connections · keys stored in the OS keychain, never in code" />

      <Card className="mb-4 border-warning/30 bg-warning/5">
        <div className="flex items-start gap-3">
          <Lock size={18} className="mt-0.5 text-warning" />
          <div className="text-sm text-cyber-text-dim">
            <div className="font-bold text-warning">Keys never leave your machine</div>
            {native ? (
              <>
                Saved keys go into the <span className="text-accent">Windows Credential Manager</span> and
                are read back only by the connector that owns them (Phase 2) — never shown here, never
                logged. Storing keys does <span className="text-accent">not</span> enable live trading; that
                still needs a per-strategy confirmation. Read <span className="text-accent">SAFETY.md</span> first.
              </>
            ) : (
              <>
                You're in the <span className="text-accent">browser build</span>, which has no OS keychain —
                key storage is disabled here. Run the desktop app (<span className="text-accent">npm run tauri dev</span>)
                to store keys securely. Read <span className="text-accent">SAFETY.md</span> before going live.
              </>
            )}
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {VENUES.map((v) => (
          <VenueCard key={v.id} v={v} native={native} connected={!!status[v.id]} onChanged={refresh} />
        ))}
      </div>

      {native && status["alpaca-live"] && (
        <Card className="mt-4 border-danger/30 bg-danger/5">
          <div className="flex items-start gap-3">
            <TriangleAlert size={18} className="mt-0.5 shrink-0 text-danger" />
            <div className="text-sm text-cyber-text-dim">
              <div className="font-bold text-danger text-glow-red">Live keys are stored</div>
              Switch endpoints on the <span className="text-accent">Live</span> page — it needs a typed{" "}
              <span className="text-danger font-bold">ARM LIVE</span> for real money, and the endpoint can only be
              changed while disarmed. Storing keys here does not route a single order.
            </div>
          </div>
        </Card>
      )}

      <div className="mt-4">
        <AiProvidersCard />
      </div>

      {native && (
        <div className="mt-4">
          <PreferencesCard />
        </div>
      )}

      <div className="mt-4">
        <AlertsCard native={native} />
      </div>
    </div>
  );
}

/**
 * Data-feed and AI-overlay settings.
 *
 * Desktop only, and deliberately so: the backend-server build reads the same
 * settings from its environment, and having two competing sources of truth for
 * "which feed am I on" is how you end up debugging the wrong one.
 */
function PreferencesCard() {
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    getPrefs()
      .then((p) => {
        setPrefs(p);
        setLoaded(true);
      })
      .catch((e) => setMsg(String(e)));
  }, []);

  function set<K extends keyof Prefs>(key: K, value: Prefs[K]) {
    setPrefs((p) => ({ ...p, [key]: value }));
    setMsg("");
  }

  async function save() {
    setBusy(true);
    setMsg("");
    try {
      // The daemon sanitizes on the way in, so adopt what it actually stored —
      // otherwise the form can keep showing a value that was corrected.
      setPrefs(await savePrefs(prefs));
      setMsg("saved — the daemon picks these up on its next pass, no restart");
    } catch (e) {
      setMsg(`error: ${String(e instanceof Error ? e.message : e)}`);
    }
    setBusy(false);
  }

  return (
    <Card title="Data & AI overlay" right={<SlidersHorizontal size={14} className="text-accent" />}>
      <div className="mb-3 text-sm text-cyber-text-dim">
        Stored beside your keys and loaded automatically on every start. Nothing here is secret.
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <Field label="Alpaca data feed" hint="iex is the free tier; sip needs a paid subscription">
          <Select value={prefs.alpacaFeed} onChange={(v) => set("alpacaFeed", v)} options={["iex", "sip"]} />
        </Field>

        <Field label="Candle size" hint="the bars every indicator runs on">
          <Select value={prefs.barTimeframe} onChange={(v) => set("barTimeframe", v)} options={TIMEFRAMES} />
        </Field>

        <Field label="AI provider" hint="which model the background overlay polls">
          <Select
            value={prefs.aiProvider}
            onChange={(v) => set("aiProvider", v)}
            options={["anthropic", "openai", "xai", "zai", "deepseek", "google", "groq", "openrouter", "mistral", "ollama"]}
          />
        </Field>

        <Field label="AI model" hint="blank = that provider's default">
          <input
            value={prefs.aiModel}
            onChange={(e) => set("aiModel", e.target.value)}
            placeholder="claude-opus-5"
            className="w-full rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
          />
        </Field>

        <Field label="Thinking effort" hint="low keeps the answer inside its bar">
          <Select value={prefs.aiEffort} onChange={(v) => set("aiEffort", v)} options={EFFORTS} />
        </Field>

        <Field label="Poll interval (s)" hint="one market per pass — this is the cost dial">
          <input
            type="number"
            min={30}
            max={86400}
            value={prefs.aiIntervalSec}
            onChange={(e) => set("aiIntervalSec", Number(e.target.value))}
            className="w-full rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
          />
        </Field>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <Button tone="cyan" icon={ShieldCheck} disabled={busy || !loaded} onClick={save}>
          Save preferences
        </Button>
        {msg && <span className="text-xs text-cyber-text-dim">{msg}</span>}
      </div>
      <div className="mt-2 text-[11px] text-cyber-text-faint">
        The overlay itself stays off until you enable it on the AI Signals page — these settings only
        decide how it behaves once you do.
      </div>
    </Card>
  );
}

function Field({ label, hint, children }: { label: string; hint: string; children: ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-xs text-cyber-text-dim">{label}</label>
      {children}
      <div className="mt-1 text-[10px] text-cyber-text-faint">{hint}</div>
    </div>
  );
}

function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
    >
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

function AiProvidersCard() {
  const mode = aiMode();
  const [providers, setProviders] = useState<LlmProviderInfo[]>([]);
  const [err, setErr] = useState("");

  async function refresh() {
    if (mode === "none") return;
    try {
      setProviders(await aiProviders());
    } catch (e) {
      setErr(String(e));
    }
  }
  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Card
      title="AI providers"
      right={<BrainCircuit size={14} className="text-purple-neon" />}
    >
      <div className="mb-3 text-sm text-cyber-text-dim">
        Bring any API key — <span className="text-accent">Claude, GPT, Grok, GLM, Gemini, DeepSeek, Groq, Mistral,
        OpenRouter</span> or a local <span className="text-accent">Ollama</span>. Used on the{" "}
        <span className="text-accent">AI Signals</span> page to reason about markets. Keys are advisory only —
        they never place orders.
      </div>

      {mode === "none" ? (
        <div className="rounded border border-warning/30 bg-warning/5 px-3 py-2 text-xs text-cyber-text-dim">
          The browser paper build can't reach model APIs. Run the <span className="text-accent">desktop app</span>{" "}
          (keys in the OS keychain) or a <span className="text-accent">backend server</span> (keys in its env).
        </div>
      ) : mode === "server" ? (
        <div className="rounded border border-accent/20 bg-accent/5 px-3 py-2 text-xs text-cyber-text-dim">
          Connected to a backend — provider keys live in the <span className="text-accent">server's environment</span>{" "}
          (e.g. <code className="text-accent">ANTHROPIC_API_KEY</code>, <code className="text-accent">OPENAI_API_KEY</code>,{" "}
          <code className="text-accent">XAI_API_KEY</code>). Configured providers show a green badge below.
        </div>
      ) : null}

      <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-2">
        {providers.map((p) => (
          <ProviderRow key={p.id} p={p} manageable={mode === "native"} onChanged={refresh} />
        ))}
      </div>
      {err && <div className="mt-2 text-xs text-danger">{err}</div>}
    </Card>
  );
}

function ProviderRow({
  p,
  manageable,
  onChanged,
}: {
  p: LlmProviderInfo;
  manageable: boolean;
  onChanged: () => Promise<void>;
}) {
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  // null while nothing has been asserted; true/false colours the result.
  const [ok, setOk] = useState<boolean | null>(null);

  async function save() {
    setBusy(true);
    setMsg("");
    setOk(null);
    try {
      await saveAiKey(p.id, val);
      setVal("");
      setMsg("saved");
      await onChanged();
    } catch (e) {
      setMsg(String(e instanceof Error ? e.message : e));
      setOk(false);
    }
    setBusy(false);
  }
  async function test() {
    setBusy(true);
    setMsg("testing…");
    setOk(null);
    try {
      setMsg(await testLlmKey(p.id));
      setOk(true);
    } catch (e) {
      setMsg(String(e instanceof Error ? e.message : e));
      setOk(false);
    }
    setBusy(false);
  }
  async function clear() {
    setBusy(true);
    setMsg("");
    setOk(null);
    try {
      await clearAiKey(p.id);
      setMsg("cleared");
      await onChanged();
    } catch (e) {
      setMsg(String(e instanceof Error ? e.message : e));
      setOk(false);
    }
    setBusy(false);
  }

  return (
    <div className="rounded-lg border border-cyber-border bg-cyber-surface/40 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium">{p.label}</span>
        <Badge tone={p.configured ? "green" : "neutral"}>{p.configured ? "configured" : p.needsKey ? "no key" : "local"}</Badge>
      </div>
      <div className="mb-2 text-[11px] text-cyber-text-faint">
        default model <span className="text-cyber-text-dim">{p.defaultModel}</span>
        {p.needsKey && <> · env <code className="text-cyber-text-dim">{p.envKey}</code></>}
      </div>
      {p.needsKey && manageable ? (
        <>
          <input
            type="password"
            value={val}
            autoComplete="off"
            onChange={(e) => {
              setVal(e.target.value);
              setMsg("");
            }}
            placeholder={p.configured ? "•••••••• (stored)" : "paste API key"}
            className="w-full rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
          />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button tone="cyan" icon={ShieldCheck} disabled={busy || val.trim().length === 0} onClick={save}>
              {p.configured ? "Update" : "Save"}
            </Button>
            {p.configured && (
              <Button tone="purple" icon={PlugZap} disabled={busy} onClick={test}>
                Test
              </Button>
            )}
            {p.configured && (
              <Button tone="red" icon={Trash2} disabled={busy} onClick={clear}>
                Clear
              </Button>
            )}
          </div>
          {msg && (
            <div className={`mt-2 text-xs ${ok === false ? "text-danger" : ok ? "text-success" : "text-cyber-text-dim"}`}>
              {msg}
            </div>
          )}
        </>
      ) : !p.needsKey ? (
        <div className="text-[11px] text-cyber-text-dim">No key needed — runs against your local Ollama.</div>
      ) : null}
    </div>
  );
}

function AlertsCard({ native }: { native: boolean }) {
  const [url, setUrl] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function save() {
    setBusy(true);
    setMsg("");
    try {
      await invoke("save_venue_keys", { venue: "alerts", fields: { webhook: url } });
      setUrl("");
      setSaved(true);
      setMsg("webhook saved");
    } catch (e) {
      setMsg(`error: ${String(e)}`);
    }
    setBusy(false);
  }
  async function test() {
    setBusy(true);
    setMsg("");
    try {
      await invoke("test_alert");
      setMsg("test alert sent — check your channel");
    } catch (e) {
      setMsg(`error: ${String(e)}`);
    }
    setBusy(false);
  }
  async function clear() {
    setBusy(true);
    try {
      await invoke("clear_venue_keys", { venue: "alerts" });
      setSaved(false);
      setUrl("");
      setMsg("cleared");
    } catch (e) {
      setMsg(`error: ${String(e)}`);
    }
    setBusy(false);
  }

  return (
    <Card title="Discord / Webhook Alerts" right={<Bell size={14} className="text-purple-neon" />}>
      {!native ? (
        <div className="text-sm text-cyber-text-dim">
          Alerts are available in the <span className="text-accent">desktop app</span> only — a browser can't
          POST to Discord (CORS). Run <span className="text-accent">npm run tauri dev</span> to enable them.
        </div>
      ) : (
        <>
          <div className="mb-2 text-sm text-cyber-text-dim">
            Get a message on every fill, position exit and risk trip (kill switch, drawdown breaker, cooldown).
            Paste a Discord webhook URL (or any endpoint that accepts <code className="text-accent">{"{ content }"}</code> JSON).
          </div>
          <input
            type="password"
            value={url}
            autoComplete="off"
            onChange={(e) => {
              setUrl(e.target.value);
              setSaved(false);
            }}
            placeholder={saved ? "•••••••• (stored)" : "https://discord.com/api/webhooks/…"}
            className="w-full rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
          />
          <div className="mt-3 flex items-center gap-2">
            <Button tone="purple" icon={ShieldCheck} disabled={busy || url.trim().length === 0} onClick={save}>
              Save webhook
            </Button>
            <Button tone="cyan" icon={Send} disabled={busy} onClick={test}>
              Send test
            </Button>
            <Button tone="red" icon={Trash2} disabled={busy} onClick={clear}>
              Clear
            </Button>
            {msg && <span className="text-xs text-cyber-text-dim">{msg}</span>}
          </div>
          <div className="mt-2 text-[11px] text-cyber-text-faint">
            The URL is stored in the OS keychain and only sent to the host you provide.
          </div>
        </>
      )}
    </Card>
  );
}

function VenueCard({
  v,
  native,
  connected,
  onChanged,
}: {
  v: VenueCfg;
  native: boolean;
  connected: boolean;
  onChanged: () => Promise<void>;
}) {
  const [vals, setVals] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [ok, setOk] = useState<boolean | null>(null);
  const filled = v.fields.every((f) => (vals[f.key] ?? "").trim().length > 0);

  const isAlpaca = v.id === "alpaca" || v.id === "alpaca-live";
  const isPaperSlot = v.id === "alpaca";

  /**
   * Read-only account check against **this card's own endpoint**.
   *
   * Only Alpaca has one, because it's the only venue here that routes real
   * orders — and a key that saved fine but is rejected at the broker is
   * indistinguishable from a working one until the first trade doesn't happen.
   */
  async function test() {
    setBusy(true);
    setMsg("testing…");
    setOk(null);
    try {
      const a = await alpacaAccount(isPaperSlot);
      setMsg(
        `${a.status} · equity $${Number(a.equity || a.portfolioValue).toLocaleString()} · buying power $${Number(
          a.buyingPower
        ).toLocaleString()} · ${a.paper ? "paper" : "LIVE"} endpoint`
      );
      setOk(a.status === "ACTIVE");
    } catch (e) {
      setMsg(
        `${String(e instanceof Error ? e.message : e)} — a 401 here usually means ${
          isPaperSlot ? "live keys pasted into the paper slot" : "paper keys pasted into the live slot"
        }`
      );
      setOk(false);
    }
    setBusy(false);
  }

  async function save() {
    setBusy(true);
    setMsg("");
    try {
      if (native) {
        await invoke("save_venue_keys", { venue: v.id, fields: vals });
        setVals({}); // don't keep secrets in component memory
        setMsg("saved to OS keychain");
        await onChanged();
      } else {
        setMsg("desktop app only — no keychain in the browser");
      }
    } catch (e) {
      setMsg(`error: ${String(e)}`);
    }
    setBusy(false);
  }

  async function clear() {
    setBusy(true);
    setMsg("");
    try {
      if (native) {
        await invoke("clear_venue_keys", { venue: v.id });
        setVals({});
        setMsg("cleared from keychain");
        await onChanged();
      }
    } catch (e) {
      setMsg(`error: ${String(e)}`);
    }
    setBusy(false);
  }

  return (
    <Card
      title={v.name}
      right={<Badge tone={connected ? "green" : "neutral"}>{connected ? "connected" : "not connected"}</Badge>}
    >
      <div className="space-y-2">
        {v.fields.map((f) => (
          <div key={f.key}>
            <label className="mb-1 flex items-center gap-1 text-xs text-cyber-text-dim">
              {f.secret ? <KeyRound size={11} /> : <Link2 size={11} />}
              {f.label}
            </label>
            <input
              type={f.secret ? "password" : "text"}
              value={vals[f.key] ?? ""}
              autoComplete="off"
              onChange={(e) => {
                setVals((s) => ({ ...s, [f.key]: e.target.value }));
                setMsg("");
              }}
              placeholder={connected ? "•••••••• (stored)" : f.secret ? "••••••••" : ""}
              className="w-full rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
            />
          </div>
        ))}
      </div>
      <div className="mt-2 text-[11px] leading-snug text-cyber-text-faint">{v.note}</div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button tone="cyan" icon={ShieldCheck} disabled={!filled || busy} onClick={save}>
          {connected ? "Update keys" : "Save to vault"}
        </Button>
        {native && connected && isAlpaca && (
          <Button tone="purple" icon={PlugZap} disabled={busy} onClick={test}>
            Test
          </Button>
        )}
        {native && connected && (
          <Button tone="red" icon={Trash2} disabled={busy} onClick={clear}>
            Clear
          </Button>
        )}
      </div>
      {msg && (
        <div className={`mt-2 text-xs ${ok === false ? "text-danger" : ok ? "text-success" : "text-cyber-text-dim"}`}>
          {msg}
        </div>
      )}
    </Card>
  );
}
