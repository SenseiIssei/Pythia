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
import {
  Card,
  PageHeader,
  Badge,
  Button,
  EmptyState,
  Field,
  Loading,
  Notice,
  Term,
  fmtUsd,
  inputCls,
} from "../components/ui";
import {
  liveMode,
  walletSnapshot,
  walletAddresses,
  saveWalletAddresses,
} from "../live";
import { useStore } from "../store";
import { useAdvanced } from "../uiMode";
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
  const advanced = useAdvanced();
  const { portfolio } = useStore();
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

  const header = (
    <PageHeader
      title="Money"
      subtitle={
        advanced
          ? "Broker, exchanges and watch-only addresses on one balance sheet."
          : "Your real accounts in one place: what is in them, and whether Pythia could trade there."
      }
    />
  );

  if (mode === "none") {
    return (
      <div className="animate-fade-in mx-auto max-w-4xl space-y-4">
        {header}
        <Card>
          <div className="text-sm text-cyber-text-dim">Practice balance</div>
          <div className="mt-1 font-mono text-3xl font-bold tabular-nums">{fmtUsd(portfolio.equity)}</div>
          <p className="mt-1 text-xs text-cyber-text-faint">Fake money. This is the only balance the browser version has.</p>
        </Card>
        <Card>
          <EmptyState icon={Wallet} title="Real account balances need the desktop app">
            Reading a broker, an exchange or a crypto address needs either the desktop app (keys stay in your
            computer's keychain) or a connected server. This browser version never sees a real account.
          </EmptyState>
        </Card>
      </div>
    );
  }

  const accounts = snap?.accounts ?? [];
  return (
    <div className="animate-fade-in mx-auto max-w-4xl space-y-4">
      {header}

      <Notice tone="info" icon={ShieldCheck} title={advanced ? "Read-only, and self-custody stays self-custody" : "Pythia can look, not take"}>
        {advanced ? (
          <>
            Pythia never asks for a seed phrase or a private key. On-chain wallets are watched by public address: it can
            see them, it cannot move them. Trading happens only at venues where you hold a{" "}
            <span className="text-accent">revocable API key</span>, so a compromised Pythia costs you a key rotation,
            not your coins.
          </>
        ) : (
          <>
            It never asks for a seed phrase or a private key. Crypto wallets are watched by their public address, which
            lets it see a balance but never move it. Where it can trade, it uses a key you can switch off at any time.
          </>
        )}
      </Notice>

      <Card>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <div className="text-sm text-cyber-text-dim">Total across your accounts</div>
            {snap ? (
              <>
                <div className="mt-1 font-mono text-3xl font-bold tabular-nums">{fmtUsd(snap.usdTotal)}</div>
                <div className="mt-0.5 text-xs text-cyber-text-faint">
                  {snap.accounts.length} account{snap.accounts.length === 1 ? "" : "s"}
                  {snap.updatedAt > 0 && `, read at ${new Date(snap.updatedAt).toLocaleTimeString()}`}
                </div>
              </>
            ) : busy ? (
              <Loading>Reading balances</Loading>
            ) : (
              <div className="mt-1 text-sm text-cyber-text-faint">Not read yet.</div>
            )}
          </div>
          <Button tone="cyan" icon={RefreshCw} disabled={busy} onClick={() => void refresh()}>
            {busy ? "Reading" : "Refresh"}
          </Button>
        </div>
      </Card>

      {err && (
        <Notice tone="danger" icon={TriangleAlert} title="Could not read the balances">
          {err}
        </Notice>
      )}

      {snap?.unpriced.length ? (
        <Notice tone="warning" title="Some coins have no dollar price">
          {snap.unpriced.join(", ")} {snap.unpriced.length === 1 ? "is" : "are"} held but left out of the total rather
          than counted as zero.
        </Notice>
      ) : null}

      {snap && accounts.length === 0 && (
        <Card>
          <EmptyState icon={Wallet} title="Nothing connected yet">
            Add broker or exchange keys in Settings{mode === "native" ? ", or watch a crypto address below" : ""}. Until
            then Pythia only trades with practice money.
          </EmptyState>
        </Card>
      )}
      {accounts.map((a) => (
        <AccountCard key={a.id} account={a} />
      ))}

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
          {account.canTrade ? (
            <Badge tone="green" title="Pythia holds a key that can place orders here">
              can trade
            </Badge>
          ) : (
            <Badge tone="neutral" title="Pythia can see the balance but cannot move anything">
              watch only
            </Badge>
          )}
          <span className="font-mono text-sm font-bold">{fmtUsd(account.usdTotal)}</span>
        </div>
      }
    >
      <div className="mb-2 flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-widest text-cyber-text-faint">
        <Icon size={12} aria-hidden /> {account.provider}
      </div>
      {account.error ? (
        <div className="text-sm text-danger">{account.error}</div>
      ) : nonZero.length === 0 ? (
        <div className="text-sm text-cyber-text-faint">Empty: no balance in this account.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="font-mono text-[10px] uppercase tracking-widest text-cyber-text-faint">
                <th className="py-1 text-left font-normal">Asset</th>
                <th className="py-1 text-right font-normal"><Term>Free</Term></th>
                <th className="py-1 text-right font-normal"><Term>Total</Term></th>
                <th className="py-1 text-right font-normal"><Term>USD</Term></th>
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
                      <span className="text-cyber-text-faint" title="No dollar price available">-</span>
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
      setErr("That address is already watched on this network.");
      return;
    }
    await persist([...list, { chain, address: a, label: label.trim() }]);
    setAddress("");
    setLabel("");
  }

  return (
    <Card
      title="Watch an address"
      icon={Wallet}
      subtitle={
        <>
          Paste a <b>public address</b>. Pythia reads the chain's own coin balance and nothing else: no key, no signing,
          no way to spend.
        </>
      }
    >
      <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)_minmax(0,10rem)_auto] sm:items-end">
        <Field label="Network">
          <select value={chain} onChange={(e) => setChain(e.target.value as Chain)} className={inputCls}>
            {CHAINS.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label} ({c.asset})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Public address">
          <input
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="0x… / bc1… / base58"
            spellCheck={false}
            className={`${inputCls} font-mono`}
          />
        </Field>
        <Field label="Name (optional)">
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. cold wallet" className={inputCls} />
        </Field>
        <Button tone="cyan" icon={Plus} onClick={() => void add()} disabled={!address.trim()}>
          Add
        </Button>
      </div>
      {err && <div className="mb-2 text-sm text-danger">{err}</div>}
      {undoNotice}

      {list.length === 0 ? (
        <div className="text-sm text-cyber-text-faint">No addresses watched yet.</div>
      ) : (
        <div className="space-y-1.5">
          {list.map((w, i) => (
            <div
              key={`${w.chain}:${w.address}`}
              className="flex items-center justify-between gap-3 rounded-lg border border-cyber-border bg-cyber-bg/40 px-3 py-2 text-sm"
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
                size="sm"
                icon={Trash2}
                ariaLabel={`Stop watching ${w.label || w.address}`}
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
