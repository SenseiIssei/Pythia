import { useState } from "react";
import { KeyRound, Lock, Link2, ShieldCheck } from "lucide-react";
import { Card, PageHeader, Badge, Button } from "../components/ui";

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
  return (
    <div className="animate-fade-in">
      <PageHeader title="Settings" subtitle="Venue connections · keys stored in the OS keychain, never in code" />

      <Card className="mb-4 border-warning/30 bg-warning/5">
        <div className="flex items-start gap-3">
          <Lock size={18} className="mt-0.5 text-warning" />
          <div className="text-sm text-cyber-text-dim">
            <div className="font-bold text-warning">Keys never leave your machine</div>
            In the native build, these save to the OS keychain (Windows Credential Manager) and are
            sent only to the venue they belong to. This paper build stores nothing and places no real
            orders. Read <span className="text-accent">SAFETY.md</span> before arming anything live.
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {VENUES.map((v) => (
          <VenueCard key={v.id} v={v} />
        ))}
      </div>
    </div>
  );
}

function VenueCard({ v }: { v: VenueCfg }) {
  const [vals, setVals] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);
  const filled = v.fields.every((f) => (vals[f.key] ?? "").length > 0);

  return (
    <Card
      title={v.name}
      right={<Badge tone={saved ? "green" : "neutral"}>{saved ? "saved" : "not connected"}</Badge>}
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
              onChange={(e) => {
                setVals((s) => ({ ...s, [f.key]: e.target.value }));
                setSaved(false);
              }}
              placeholder={f.secret ? "••••••••" : ""}
              className="w-full rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
            />
          </div>
        ))}
      </div>
      <div className="mt-2 text-[11px] leading-snug text-cyber-text-faint">{v.note}</div>
      <div className="mt-3 flex items-center gap-2">
        <Button tone="cyan" icon={ShieldCheck} disabled={!filled} onClick={() => setSaved(true)}>
          Save to vault
        </Button>
        {saved && <span className="text-xs text-success">stored locally (mock)</span>}
      </div>
    </Card>
  );
}
