import { useCallback, useEffect, useState, type ReactNode } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  Lock,
  ShieldCheck,
  Trash2,
  Bell,
  Send,
  BrainCircuit,
  Building2,
  Landmark,
  PlugZap,
  SlidersHorizontal,
  TriangleAlert,
  Eye,
} from "lucide-react";
import { Card, PageHeader, Badge, Button, Field, Notice, inputCls } from "../components/ui";
import { ComfortZone } from "../components/ComfortZone";
import { ConfirmButton } from "../components/Confirm";
import { isTauri } from "../engine";
import { setUiMode, useAdvanced, type UiMode } from "../uiMode";
import { aiMode, aiProviders, saveAiKey, clearAiKey } from "../ai";
import { alpacaAccount, listExchanges, saveExchangeKeys, clearExchangeKeys } from "../live";
import { DEFAULT_PREFS, EFFORTS, TIMEFRAMES, getPrefs, savePrefs, testLlmKey, type Prefs } from "../prefs";
import type { ExchangeInfo, LlmProviderInfo } from "../types";

interface VenueCfg {
  id: string;
  name: string;
  fields: { key: string; label: string; secret?: boolean }[];
  note: string;
}

const VENUES: VenueCfg[] = [
  {
    id: "alpaca",
    name: "Alpaca paper account",
    fields: [
      { key: "keyId", label: "API key id" },
      { key: "secret", label: "API secret", secret: true },
    ],
    note: "Keys from the Paper Trading account (paper-api.alpaca.markets). Real API, real order lifecycle, fake money.",
  },
  {
    id: "alpaca-live",
    name: "Alpaca live account (real money)",
    fields: [
      { key: "keyId", label: "API key id" },
      { key: "secret", label: "API secret", secret: true },
    ],
    note: "Real money. Keys from the Live account, which is a different pair from the paper ones. Storing them changes nothing on its own: routing still needs a typed ARM LIVE on the Live page.",
  },
];

/** A heading between groups of cards, so a long settings page reads in parts. */
function Group({ title, children, intro }: { title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-4">
      <div className="border-b border-cyber-border pb-2 pt-2">
        <h2 className="font-mono text-xs font-bold uppercase tracking-widest text-cyber-text-dim">{title}</h2>
        {intro && <p className="mt-1 text-sm text-cyber-text-faint">{intro}</p>}
      </div>
      {children}
    </section>
  );
}

export function Settings() {
  const native = isTauri();
  const advanced = useAdvanced();
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
    <div className="animate-fade-in mx-auto max-w-5xl space-y-6">
      <PageHeader
        title="Settings"
        subtitle={
          advanced
            ? "View, safety limits, venue connections and AI providers. Keys are stored in the OS keychain, never in code."
            : "How much to show, how careful to be, and (only when you want it) connections to real accounts."
        }
      />

      <Group title="You">
        <ViewModeCard advanced={advanced} />
        <ComfortZone />
      </Group>

      <Group
        title="Connections"
        intro={
          advanced
            ? "Broker, exchange and AI keys. None of them turns on live trading by itself."
            : "Optional. Only needed to see or trade real accounts. You can skip all of this while you practise."
        }
      >
        <Notice tone="warning" icon={Lock} title="Keys never leave your machine">
          {native ? (
            <>
              Saved keys go into the <span className="text-accent">Windows Credential Manager</span> and are read back
              only by the connector that owns them. They are never shown here and never logged. Storing keys does{" "}
              <b className="text-cyber-text">not</b> turn on live trading; that still needs a per-strategy confirmation.
              Read <span className="text-accent">SAFETY.md</span> first.
            </>
          ) : (
            <>
              This is the <span className="text-accent">browser version</span>, which has no keychain, so keys cannot be
              stored here. The desktop app (<code className="text-accent">npm run tauri dev</code>) stores them safely.
              Read <span className="text-accent">SAFETY.md</span> before going live.
            </>
          )}
        </Notice>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {VENUES.map((v) => (
            <VenueCard key={v.id} v={v} native={native} connected={!!status[v.id]} onChanged={refresh} />
          ))}
        </div>

        {native && status["alpaca-live"] && (
          <Notice tone="danger" icon={TriangleAlert} title="Live keys are stored">
            Switch endpoints on the <span className="text-accent">Live</span> page. Real money needs a typed{" "}
            <b className="text-danger">ARM LIVE</b>, and the endpoint can only be changed while disarmed. Storing keys
            here does not route a single order.
          </Notice>
        )}

        <ExchangesCard native={native} onChanged={refresh} />

        <AiProvidersCard />

        {native && <PreferencesCard />}

        {/* Webhooks are an integration, not a setting: nothing a first-time user
            needs in order to understand or use the app. */}
        {advanced && <AlertsCard native={native} />}
      </Group>
    </div>
  );
}

/**
 * The view switch. First card on the page on purpose: it is the setting that
 * changes the most about how the app reads, and someone who feels lost needs to
 * find it without knowing what to look for.
 */
function ViewModeCard({ advanced }: { advanced: boolean }) {
  const options: { id: UiMode; label: string; body: string }[] = [
    {
      id: "simple",
      label: "Simple",
      body: "Only what you need to understand what the app is doing with your money.",
    },
    {
      id: "advanced",
      label: "Advanced",
      body: "Everything: markets, positions, strategies, backtests, the optimizer, risk limits and the full journal.",
    },
  ];
  const current: UiMode = advanced ? "advanced" : "simple";
  return (
    <Card title="How much to show" icon={Eye}>
      <div role="radiogroup" aria-label="How much to show" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {options.map((o) => {
          const on = current === o.id;
          return (
            <button
              key={o.id}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => setUiMode(o.id)}
              className={`rounded-lg border px-3 py-2.5 text-left transition-colors ${
                on
                  ? "border-accent/50 bg-accent/10"
                  : "border-cyber-border bg-cyber-bg/40 hover:border-cyber-border-bright"
              }`}
            >
              <div className="flex items-center gap-2">
                <span
                  aria-hidden
                  className={`flex h-3.5 w-3.5 items-center justify-center rounded-full border ${
                    on ? "border-accent" : "border-cyber-text-faint"
                  }`}
                >
                  {on && <span className="h-1.5 w-1.5 rounded-full bg-accent" />}
                </span>
                <span className={`text-sm font-semibold ${on ? "text-accent" : "text-cyber-text"}`}>{o.label}</span>
              </div>
              <p className="mt-1 pl-5 text-xs leading-relaxed text-cyber-text-dim">{o.body}</p>
            </button>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-cyber-text-faint">
        This changes only what you can see and adjust, never how the app behaves. The same switch sits at the bottom of
        the menu.
      </p>
    </Card>
  );
}

/**
 * Crypto exchanges. One is active at a time (whichever was saved last) because
 * `Venue::Crypto` routes to exactly one book, and quietly splitting orders
 * across venues would make position sizing a lie.
 */
function ExchangesCard({ native, onChanged }: { native: boolean; onChanged: () => Promise<void> }) {
  const [list, setList] = useState<ExchangeInfo[]>([]);
  const [err, setErr] = useState("");

  const refresh = useCallback(async () => {
    try {
      setList(await listExchanges());
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <Card
      title="Crypto exchanges"
      icon={Building2}
      subtitle={
        <>
          Pick the one exchange where crypto orders go. Saving keys selects it; the markets and strategies stay the same,
          so a strategy proven on one exchange can be pointed at another. Give the key permission to{" "}
          <b className="text-cyber-text">trade</b> and <b className="text-cyber-text">not</b> to withdraw: then a leaked
          key costs you trades, not coins.
        </>
      }
    >
      {!native && (
        <div className="mb-3 rounded-lg border border-accent/20 bg-accent/5 px-3 py-2 text-xs leading-relaxed text-cyber-text-dim">
          On a backend, exchange keys come from its environment: <code className="text-accent">PYTHIA_EXCHANGE</code>,{" "}
          <code className="text-accent">PYTHIA_EXCHANGE_KEY</code>, <code className="text-accent">PYTHIA_EXCHANGE_SECRET</code>{" "}
          (plus <code className="text-accent">PYTHIA_EXCHANGE_PASSPHRASE</code> for OKX).
        </div>
      )}

      {list.length === 0 && !err && <div className="text-sm text-cyber-text-faint">Loading the list of exchanges.</div>}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {list.map((ex) => (
          <ExchangeRow
            key={ex.id}
            ex={ex}
            manageable={native}
            onChanged={async () => {
              await refresh();
              await onChanged();
            }}
          />
        ))}
      </div>
      {err && <div className="mt-2 text-sm text-danger">Could not list the exchanges: {err}</div>}
    </Card>
  );
}

function ExchangeRow({
  ex,
  manageable,
  onChanged,
}: {
  ex: ExchangeInfo;
  manageable: boolean;
  onChanged: () => Promise<void>;
}) {
  const [vals, setVals] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [ok, setOk] = useState<boolean | null>(null);

  const needed = ["key", "secret", ...(ex.needsPassphrase ? ["passphrase"] : [])];
  const filled = needed.every((k) => (vals[k] ?? "").trim().length > 0);

  async function save() {
    setBusy(true);
    setMsg("");
    setOk(null);
    try {
      await saveExchangeKeys(ex.id, vals);
      setVals({}); // don't keep secrets in component memory
      setMsg("Saved. This is now the exchange crypto orders go to.");
      setOk(true);
      await onChanged();
    } catch (e) {
      setMsg(`Could not save: ${e instanceof Error ? e.message : String(e)}`);
      setOk(false);
    }
    setBusy(false);
  }

  async function clear() {
    setBusy(true);
    setMsg("");
    setOk(null);
    try {
      await clearExchangeKeys(ex.id);
      setVals({});
      setMsg("Keys deleted from this computer.");
      await onChanged();
    } catch (e) {
      setMsg(`Could not delete: ${e instanceof Error ? e.message : String(e)}`);
      setOk(false);
    }
    setBusy(false);
  }

  const fieldLabel = (k: string) => (k === "key" ? "API key" : k === "secret" ? "API secret" : "Passphrase");

  return (
    <div className="rounded-lg border border-cyber-border bg-cyber-bg/40 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-sm font-semibold">{ex.label}</span>
        <Badge tone={ex.configured ? "green" : "neutral"}>
          {ex.configured ? "connected" : ex.canTrade ? "no key" : "not supported yet"}
        </Badge>
      </div>

      {!ex.canTrade ? (
        <div className="text-xs leading-snug text-cyber-text-faint">
          Coinbase Advanced Trade signs with ES256 JWTs rather than an HMAC, so it is listed but cannot route orders yet.
          See PROFIT-PLAN.md.
        </div>
      ) : !manageable ? (
        <div className="text-xs text-cyber-text-faint">Managed by the server's environment.</div>
      ) : (
        <div className="space-y-2">
          {needed.map((k) => (
            <Field key={k} label={fieldLabel(k)}>
              <input
                type={k === "key" ? "text" : "password"}
                value={vals[k] ?? ""}
                autoComplete="off"
                spellCheck={false}
                onChange={(e) => {
                  setVals((s) => ({ ...s, [k]: e.target.value }));
                  setMsg("");
                }}
                placeholder={ex.configured && !vals[k] ? "•••••••• (stored)" : ""}
                className={inputCls}
              />
            </Field>
          ))}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button tone="cyan" icon={ShieldCheck} disabled={!filled || busy} onClick={save}>
              {ex.configured ? "Update keys" : "Save and use this exchange"}
            </Button>
            {ex.configured && (
              <ConfirmButton
                icon={Trash2}
                disabled={busy}
                question={`Delete the ${ex.label} keys from this computer? Pythia cannot get them back; you would paste them again to reconnect.`}
                confirmLabel="Delete keys"
                onConfirm={clear}
              >
                Clear
              </ConfirmButton>
            )}
          </div>
          {msg && (
            <div role="status" className={`text-xs ${ok === false ? "text-danger" : ok ? "text-success" : "text-cyber-text-dim"}`}>
              {msg}
            </div>
          )}
        </div>
      )}
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
  const [ok, setOk] = useState<boolean | null>(null);

  useEffect(() => {
    getPrefs()
      .then((p) => {
        setPrefs(p);
        setLoaded(true);
      })
      .catch((e) => {
        setMsg(`Could not load the preferences: ${String(e)}`);
        setOk(false);
      });
  }, []);

  function set<K extends keyof Prefs>(key: K, value: Prefs[K]) {
    setPrefs((p) => ({ ...p, [key]: value }));
    setMsg("");
  }

  async function save() {
    setBusy(true);
    setMsg("");
    setOk(null);
    try {
      // The daemon sanitizes on the way in, so adopt what it actually stored;
      // otherwise the form can keep showing a value that was corrected.
      setPrefs(await savePrefs(prefs));
      setMsg("Saved. The engine picks these up on its next pass, no restart needed.");
      setOk(true);
    } catch (e) {
      setMsg(`Could not save: ${String(e instanceof Error ? e.message : e)}`);
      setOk(false);
    }
    setBusy(false);
  }

  return (
    <Card
      title="Data and AI overlay"
      icon={SlidersHorizontal}
      subtitle="Stored beside your keys and loaded on every start. Nothing here is secret."
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <Field label="Alpaca data feed" hint="iex is the free tier; sip needs a paid subscription">
          <Select value={prefs.alpacaFeed} onChange={(v) => set("alpacaFeed", v)} options={["iex", "sip"]} />
        </Field>

        <Field label="Candle size" hint="The length of one price bar every indicator runs on">
          <Select value={prefs.barTimeframe} onChange={(v) => set("barTimeframe", v)} options={TIMEFRAMES} />
        </Field>

        <Field label="AI provider" hint="Which model the background overlay asks">
          <Select
            value={prefs.aiProvider}
            onChange={(v) => set("aiProvider", v)}
            options={["anthropic", "openai", "xai", "zai", "deepseek", "google", "groq", "openrouter", "mistral", "ollama"]}
          />
        </Field>

        <Field label="AI model" hint="Leave empty for that provider's default">
          <input
            value={prefs.aiModel}
            onChange={(e) => set("aiModel", e.target.value)}
            placeholder="claude-opus-5"
            className={inputCls}
          />
        </Field>

        <Field label="Thinking effort" hint="Low keeps the answer short and cheap">
          <Select value={prefs.aiEffort} onChange={(v) => set("aiEffort", v)} options={EFFORTS} />
        </Field>

        <Field label="Seconds between AI calls" hint="One market per call, so this is the cost dial">
          <input
            type="number"
            min={30}
            max={86400}
            value={prefs.aiIntervalSec}
            onChange={(e) => set("aiIntervalSec", Number(e.target.value))}
            className={inputCls}
          />
        </Field>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button tone="cyan" icon={ShieldCheck} disabled={busy || !loaded} onClick={save}>
          Save preferences
        </Button>
        {msg && (
          <span role="status" className={`text-xs ${ok === false ? "text-danger" : ok ? "text-success" : "text-cyber-text-dim"}`}>
            {msg}
          </span>
        )}
      </div>
      <div className="mt-2 text-xs text-cyber-text-faint">
        The overlay itself stays off until you switch it on in the AI Signals page. These settings only decide how it
        behaves once you do.
      </div>
    </Card>
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
    <select value={value} onChange={(e) => onChange(e.target.value)} className={inputCls}>
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
      icon={BrainCircuit}
      subtitle={
        <>
          Bring any API key: Claude, GPT, Grok, GLM, Gemini, DeepSeek, Groq, Mistral, OpenRouter or a local Ollama. They
          are used to reason about markets and only ever give advice: <b className="text-cyber-text">they never place
          orders</b>.
        </>
      }
    >
      {mode === "none" ? (
        <div className="rounded-lg border border-warning/30 bg-warning/[0.06] px-3 py-2 text-xs leading-relaxed text-cyber-text-dim">
          The browser version cannot reach model APIs. Use the <span className="text-accent">desktop app</span> (keys in
          the keychain) or a <span className="text-accent">backend server</span> (keys in its environment).
        </div>
      ) : mode === "server" ? (
        <div className="rounded-lg border border-accent/20 bg-accent/5 px-3 py-2 text-xs leading-relaxed text-cyber-text-dim">
          Connected to a backend: provider keys live in the <span className="text-accent">server's environment</span>{" "}
          (e.g. <code className="text-accent">ANTHROPIC_API_KEY</code>, <code className="text-accent">OPENAI_API_KEY</code>,{" "}
          <code className="text-accent">XAI_API_KEY</code>). Configured providers show a green badge below.
        </div>
      ) : null}

      {providers.length > 0 && (
        <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
          {providers.map((p) => (
            <ProviderRow key={p.id} p={p} manageable={mode === "native"} onChanged={refresh} />
          ))}
        </div>
      )}
      {err && <div className="mt-2 text-sm text-danger">Could not list the providers: {err}</div>}
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
      setMsg("Saved.");
      setOk(true);
      await onChanged();
    } catch (e) {
      setMsg(String(e instanceof Error ? e.message : e));
      setOk(false);
    }
    setBusy(false);
  }
  async function test() {
    setBusy(true);
    setMsg("Testing the key");
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
      setMsg("Key deleted from this computer.");
      await onChanged();
    } catch (e) {
      setMsg(String(e instanceof Error ? e.message : e));
      setOk(false);
    }
    setBusy(false);
  }

  return (
    <div className="rounded-lg border border-cyber-border bg-cyber-bg/40 p-3">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-sm font-semibold">{p.label}</span>
        <Badge tone={p.configured ? "green" : "neutral"}>{p.configured ? "connected" : p.needsKey ? "no key" : "local"}</Badge>
      </div>
      <div className="mb-2 text-xs text-cyber-text-faint">
        Default model <span className="font-mono text-cyber-text-dim">{p.defaultModel}</span>
        {p.needsKey && (
          <>
            {" "}
            · env <code className="text-cyber-text-dim">{p.envKey}</code>
          </>
        )}
      </div>
      {p.needsKey && manageable ? (
        <>
          <Field label={`${p.label} API key`}>
            <input
              type="password"
              value={val}
              autoComplete="off"
              spellCheck={false}
              onChange={(e) => {
                setVal(e.target.value);
                setMsg("");
              }}
              placeholder={p.configured ? "•••••••• (stored)" : "Paste the key"}
              className={inputCls}
            />
          </Field>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button tone="cyan" icon={ShieldCheck} disabled={busy || val.trim().length === 0} onClick={save}>
              {p.configured ? "Update" : "Save"}
            </Button>
            {p.configured && (
              <Button tone="purple" icon={PlugZap} disabled={busy} onClick={test} title="Send one tiny request to check the key works">
                Test
              </Button>
            )}
            {p.configured && (
              <ConfirmButton
                icon={Trash2}
                disabled={busy}
                question={`Delete the ${p.label} key from this computer? You would paste it again to use this model.`}
                confirmLabel="Delete key"
                onConfirm={clear}
              >
                Clear
              </ConfirmButton>
            )}
          </div>
          {msg && (
            <div role="status" className={`mt-2 text-xs ${ok === false ? "text-danger" : ok ? "text-success" : "text-cyber-text-dim"}`}>
              {msg}
            </div>
          )}
        </>
      ) : !p.needsKey ? (
        <div className="text-xs text-cyber-text-dim">No key needed: it runs against your local Ollama.</div>
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
      setMsg("Webhook saved.");
    } catch (e) {
      setMsg(`Could not save: ${String(e)}`);
    }
    setBusy(false);
  }
  async function test() {
    setBusy(true);
    setMsg("");
    try {
      await invoke("test_alert");
      setMsg("Test alert sent. Check your channel.");
    } catch (e) {
      setMsg(`Could not send: ${String(e)}`);
    }
    setBusy(false);
  }
  async function clear() {
    setBusy(true);
    try {
      await invoke("clear_venue_keys", { venue: "alerts" });
      setSaved(false);
      setUrl("");
      setMsg("Webhook deleted.");
    } catch (e) {
      setMsg(`Could not delete: ${String(e)}`);
    }
    setBusy(false);
  }

  return (
    <Card title="Discord and webhook alerts" icon={Bell}>
      {!native ? (
        <div className="text-sm text-cyber-text-dim">
          Alerts work in the <span className="text-accent">desktop app</span> only: a browser is not allowed to post to
          Discord (CORS). Run <code className="text-accent">npm run tauri dev</code> to use them.
        </div>
      ) : (
        <>
          <p className="mb-3 text-sm text-cyber-text-dim">
            Get a message on every fill, position exit and risk trip (kill switch, drawdown breaker, cooldown). Paste a
            Discord webhook URL, or any endpoint that accepts <code className="text-accent">{"{ content }"}</code> JSON.
          </p>
          <Field label="Webhook URL" hint="Stored in the OS keychain and only sent to the host you give here.">
            <input
              type="password"
              value={url}
              autoComplete="off"
              spellCheck={false}
              onChange={(e) => {
                setUrl(e.target.value);
                setSaved(false);
              }}
              placeholder={saved ? "•••••••• (stored)" : "https://discord.com/api/webhooks/…"}
              className={inputCls}
            />
          </Field>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button tone="purple" icon={ShieldCheck} disabled={busy || url.trim().length === 0} onClick={save}>
              Save webhook
            </Button>
            <Button tone="cyan" icon={Send} disabled={busy} onClick={test}>
              Send test
            </Button>
            <ConfirmButton
              icon={Trash2}
              disabled={busy}
              question="Delete the alert webhook? Pythia stops sending alerts until you paste a new one."
              confirmLabel="Delete webhook"
              onConfirm={clear}
            >
              Clear
            </ConfirmButton>
            {msg && (
              <span role="status" className="text-xs text-cyber-text-dim">
                {msg}
              </span>
            )}
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
   * orders, and a key that saved fine but is rejected at the broker is
   * indistinguishable from a working one until the first trade doesn't happen.
   */
  async function test() {
    setBusy(true);
    setMsg("Testing the keys");
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
        `${String(e instanceof Error ? e.message : e)}. A 401 here usually means ${
          isPaperSlot ? "live keys pasted into the paper slot" : "paper keys pasted into the live slot"
        }.`
      );
      setOk(false);
    }
    setBusy(false);
  }

  async function save() {
    setBusy(true);
    setMsg("");
    setOk(null);
    try {
      if (native) {
        await invoke("save_venue_keys", { venue: v.id, fields: vals });
        setVals({}); // don't keep secrets in component memory
        setMsg("Saved to the OS keychain.");
        setOk(true);
        await onChanged();
      } else {
        setMsg("Only the desktop app can store keys: the browser has no keychain.");
      }
    } catch (e) {
      setMsg(`Could not save: ${String(e)}`);
      setOk(false);
    }
    setBusy(false);
  }

  async function clear() {
    setBusy(true);
    setMsg("");
    setOk(null);
    try {
      if (native) {
        await invoke("clear_venue_keys", { venue: v.id });
        setVals({});
        setMsg("Deleted from the keychain.");
        await onChanged();
      }
    } catch (e) {
      setMsg(`Could not delete: ${String(e)}`);
      setOk(false);
    }
    setBusy(false);
  }

  const live = v.id === "alpaca-live";
  return (
    <Card
      title={v.name}
      icon={Landmark}
      className={live ? "border-danger/25" : ""}
      right={<Badge tone={connected ? "green" : "neutral"}>{connected ? "connected" : "not connected"}</Badge>}
    >
      <div className="space-y-2">
        {v.fields.map((f) => (
          <Field key={f.key} label={f.label}>
            <input
              type={f.secret ? "password" : "text"}
              value={vals[f.key] ?? ""}
              autoComplete="off"
              spellCheck={false}
              disabled={!native}
              onChange={(e) => {
                setVals((s) => ({ ...s, [f.key]: e.target.value }));
                setMsg("");
              }}
              placeholder={connected ? "•••••••• (stored)" : f.secret ? "••••••••" : ""}
              className={inputCls}
            />
          </Field>
        ))}
      </div>
      <div className={`mt-2 text-xs leading-snug ${live ? "text-danger/90" : "text-cyber-text-faint"}`}>{v.note}</div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button tone="cyan" icon={ShieldCheck} disabled={!filled || busy} onClick={save}>
          {connected ? "Update keys" : "Save to keychain"}
        </Button>
        {native && connected && isAlpaca && (
          <Button tone="purple" icon={PlugZap} disabled={busy} onClick={test} title="A read-only account check; places no order">
            Test
          </Button>
        )}
        {native && connected && (
          <ConfirmButton
            icon={Trash2}
            disabled={busy}
            question={`Delete the ${v.name} keys from this computer? Pythia cannot get them back; you would paste them again to reconnect.`}
            confirmLabel="Delete keys"
            onConfirm={clear}
          >
            Clear
          </ConfirmButton>
        )}
      </div>
      {msg && (
        <div role="status" className={`mt-2 text-xs ${ok === false ? "text-danger" : ok ? "text-success" : "text-cyber-text-dim"}`}>
          {msg}
        </div>
      )}
    </Card>
  );
}
