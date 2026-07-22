import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { KeyRound, Lock, Link2, ShieldCheck, Trash2, Bell, Send } from "lucide-react";
import { Card, PageHeader, Badge, Button } from "../components/ui";
import { isTauri } from "../engine";

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
    name: "Alpaca (equities)",
    fields: [
      { key: "keyId", label: "API key id" },
      { key: "secret", label: "API secret", secret: true },
    ],
    note: "Start with the paper endpoint (paper-api.alpaca.markets). PDT rules enforced by the risk manager.",
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

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {VENUES.map((v) => (
          <VenueCard key={v.id} v={v} native={native} connected={!!status[v.id]} onChanged={refresh} />
        ))}
      </div>

      <div className="mt-4">
        <AlertsCard native={native} />
      </div>
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
  const filled = v.fields.every((f) => (vals[f.key] ?? "").trim().length > 0);

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
      <div className="mt-3 flex items-center gap-2">
        <Button tone="cyan" icon={ShieldCheck} disabled={!filled || busy} onClick={save}>
          {connected ? "Update keys" : "Save to vault"}
        </Button>
        {native && connected && (
          <Button tone="red" icon={Trash2} disabled={busy} onClick={clear}>
            Clear
          </Button>
        )}
        {msg && <span className="text-xs text-cyber-text-dim">{msg}</span>}
      </div>
    </Card>
  );
}
