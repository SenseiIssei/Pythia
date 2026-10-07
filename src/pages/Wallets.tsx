import { useCallback, useEffect, useState } from "react";
import {
  Wallet,
  RefreshCw,
  TriangleAlert,
  Plus,
  Trash2,
  Landmark,
  Building2,
  Link2,
  ShieldCheck,
} from "lucide-react";
import { Card, PageHeader, Badge, Button, fmtUsd } from "../components/ui";
import {
  liveMode,
  walletSnapshot,
  walletAddresses,
  saveWalletAddresses,
} from "../live";
import type { Chain, WalletAccount, WalletKind, WalletsSnapshot, WatchedAddress } from "../types";
import { useUndo } from "../components/Confirm";

const CHAINS: { id: Chain; label: string; asset: string }[] = [
  { id: "ethereum", label: "Ethereum", asset: "ETH" },
  { id: "polygon", label: "Polygon", asset: "POL" },
  { id: "arbitrum", label: "Arbitrum One", asset: "ETH" },
  { id: "optimism", label: "Optimism", asset: "ETH" },
  { id: "base", label: "Base", asset: "ETH" },
  { id: "bsc", label: "BNB Smart Chain", asset: "BNB" },
  { id: "solana", label: "Solana", asset: "SOL" },
  { id: "bitcoin", label: "Bitcoin", asset: "BTC" },
];

const KIND_ICON: Record<WalletKind, typeof Landmark> = {
  broker: Landmark,
  exchange: Building2,
  onchain: Link2,
};

export function Wallets() {
  const mode = liveMode();
  const [snap, setSnap] = useState<WalletsSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const refresh = useCallback(async () => {
    setBusy(true);
    setErr("");
    try {
      setSnap(await walletSnapshot());
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  }, []);

  useEffect(() => {
    if (mode !== "none") void refresh();
  }, [mode, refresh]);

  if (mode === "none") {
    return (
      <div className="animate-fade-in max-w-4xl">
        <PageHeader title="Wallets" subtitle="Every account, one balance sheet" />
        <Card className="border-warning/30 bg-warning/5">
          <div className="flex items-start gap-3">
            <TriangleAlert size={18} className="mt-0.5 shrink-0 text-warning" />
            <div className="text-sm text-cyber-text-dim">
              <div className="font-bold text-warning">Not available in the browser paper build</div>
              Reading balances needs credentials. Run the <span className="text-accent">desktop app</span> or a{" "}
              <span className="text-accent">backend server</span>.
            </div>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="animate-fade-in max-w-4xl">
      <PageHeader title="Wallets" subtitle="Broker, exchanges and watch-only addresses in one place" />

      <Card className="mb-4 border-accent/20 bg-accent/5">
        <div className="flex items-start gap-3">
          <ShieldCheck size={18} className="mt-0.5 shrink-0 text-accent" />
          <div className="text-sm text-cyber-text-dim">
            <div className="font-bold text-accent">Read-only, and self-custody stays self-custody</div>
            Pythia never asks for a seed phrase or a private key. On-chain wallets are watched by public address:
            it can see them, it cannot move them. Trading happens only at venues where you hold a{" "}
            <span className="text-accent">revocable API key</span> — so a compromised Pythia costs you a key
            rotation, not your coins.
          </div>
        </div>
      </Card>

      <div className="mb-4 flex items-center gap-3">
        <Button tone="cyan" icon={RefreshCw} disabled={busy} onClick={() => void refresh()}>
          {busy ? "Reading…" : "Refresh"}
        </Button>
        {snap && (
          <>
            <div className="text-2xl font-bold text-glow">{fmtUsd(snap.usdTotal)}</div>
            <div className="text-xs text-cyber-text-faint">
              across {snap.accounts.length} account{snap.accounts.length === 1 ? "" : "s"}
              {snap.updatedAt > 0 && ` · ${new Date(snap.updatedAt).toLocaleTimeString()}`}
            </div>
          </>
        )}
      </div>
      {err && <div className="mb-4 text-sm text-danger">{err}</div>}

      {snap?.unpriced.length ? (
        <div className="mb-4 rounded-lg border border-warning/30 bg-warning/5 px-3 py-2 text-xs text-cyber-text-dim">
          No USD price for {snap.unpriced.join(", ")} — held, but excluded from the total rather than counted as
          zero.
        </div>
      ) : null}

      <div className="mb-6 space-y-3">
        {snap?.accounts.length === 0 && (
          <Card>
            <div className="text-sm text-cyber-text-dim">
              Nothing connected yet. Add broker or exchange keys in <span className="text-accent">Settings</span>,
              or watch an address below.
            </div>
          </Card>
        )}
        {snap?.accounts.map((a) => (
          <AccountCard key={a.id} account={a} />
        ))}
      </div>

      {mode === "native" && <AddressBook onSaved={() => void refresh()} />}
    </div>
  );
}

function AccountCard({ account }: { account: WalletAccount }) {
  const Icon = KIND_ICON[account.kind];
  const nonZero = account.balances.filter((b) => b.total > 0);
  return (
    <Card
      title={account.label}
      right={
        <div className="flex items-center gap-2">
          {account.canTrade ? <Badge tone="green">tradable</Badge> : <Badge tone="neutral">watch-only</Badge>}
          <span className="font-mono text-sm font-bold">{fmtUsd(account.usdTotal)}</span>
        </div>
      }
    >
      <div className="mb-2 flex items-center gap-1.5 text-[11px] uppercase tracking-widest text-cyber-text-faint">
        <Icon size={12} /> {account.provider}
      </div>
      {account.error ? (
        <div className="text-xs text-danger">{account.error}</div>
      ) : nonZero.length === 0 ? (
        <div className="text-xs text-cyber-text-faint">No balance.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] uppercase tracking-widest text-cyber-text-faint">
                <th className="py-1 text-left font-normal">Asset</th>
                <th className="py-1 text-right font-normal">Free</th>
                <th className="py-1 text-right font-normal">Total</th>
                <th className="py-1 text-right font-normal">USD</th>
              </tr>
            </thead>
            <tbody>
              {nonZero.map((b) => (
                <tr key={b.asset} className="border-t border-cyber-border/50">
                  <td className="py-1 font-medium">{b.asset}</td>
                  <td className="py-1 text-right font-mono text-cyber-text-dim">{trim(b.free)}</td>
                  <td className="py-1 text-right font-mono">{trim(b.total)}</td>
                  <td className="py-1 text-right font-mono">
                    {b.usdValue === undefined ? (
                      <span className="text-cyber-text-faint">—</span>
                    ) : (
                      fmtUsd(b.usdValue)
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/** Desktop-only editor for watch-only addresses. */
function AddressBook({ onSaved }: { onSaved: () => void }) {
  const [list, setList] = useState<WatchedAddress[]>([]);
  const [chain, setChain] = useState<Chain>("ethereum");
  const [address, setAddress] = useState("");
  const [label, setLabel] = useState("");
  const [err, setErr] = useState("");
  const [undoNotice, offerUndo] = useUndo();

  useEffect(() => {
    void walletAddresses().then(setList).catch(() => setList([]));
  }, []);

  async function persist(next: WatchedAddress[]) {
    setErr("");
    try {
      await saveWalletAddresses(next);
      setList(next);
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function add() {
    const a = address.trim();
    if (!a) return;
    if (list.some((w) => w.chain === chain && w.address.toLowerCase() === a.toLowerCase())) {
      setErr("that address is already watched on this chain");
      return;
    }
    await persist([...list, { chain, address: a, label: label.trim() }]);
    setAddress("");
    setLabel("");
  }

  return (
    <Card title="Watch an address" right={<Wallet size={14} className="text-accent" />}>
      <div className="mb-3 text-sm text-cyber-text-dim">
        Paste a <b>public address</b>. Pythia reads the chain's native balance and nothing else — no key, no
        signing, no way to spend.
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select
          value={chain}
          onChange={(e) => setChain(e.target.value as Chain)}
          className="rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
        >
          {CHAINS.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label} ({c.asset})
            </option>
          ))}
        </select>
        <input
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="0x… / bc1… / base58"
          className="min-w-[18rem] flex-1 rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 font-mono text-sm focus:border-accent focus:outline-none"
        />
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="label (optional)"
          className="w-40 rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
        />
        <Button tone="cyan" icon={Plus} onClick={() => void add()}>
          Add
        </Button>
      </div>
      {err && <div className="mb-2 text-xs text-danger">{err}</div>}
      {undoNotice}

      {list.length > 0 && (
        <div className="space-y-1">
          {list.map((w, i) => (
            <div
              key={`${w.chain}:${w.address}`}
              className="flex items-center justify-between rounded border border-cyber-border bg-cyber-surface/40 px-3 py-1.5 text-sm"
            >
              <div className="min-w-0">
                <div className="truncate font-mono text-xs">{w.address}</div>
                <div className="text-[11px] text-cyber-text-faint">
                  {CHAINS.find((c) => c.id === w.chain)?.label ?? w.chain}
                  {w.label && ` · ${w.label}`}
                </div>
              </div>
              <Button
                tone="red"
                icon={Trash2}
                onClick={() => {
                  const before = list;
                  void persist(list.filter((_, j) => j !== i));
                  offerUndo(`Stopped watching ${w.label || w.address.slice(0, 10) + "…"}.`, () => void persist(before));
                }}
              >
                Remove
              </Button>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

/** Crypto amounts need more decimals than money, but not eight zeros of noise. */
function trim(n: number): string {
  if (n === 0) return "0";
  if (Math.abs(n) >= 1) return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
  return n.toFixed(8).replace(/0+$/, "").replace(/\.$/, "");
}
