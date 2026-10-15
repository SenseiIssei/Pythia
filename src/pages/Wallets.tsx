import { useCallback, useEffect, useState } from "react";
import { Wallet, RefreshCw, TriangleAlert, Plus, Trash2, Landmark, Building2, Link2, ShieldCheck } from "lucide-react";
import { Badge, Button, Card, Field, List, ListRow, Notice, Page, inputCls, money } from "../design";
import { KeyStats, LoadingRows, Nothing, Section, Term, plural, useUndoNote } from "../pagekit";
import { heldBalances, shortAddress, trimQty, walletCounts } from "../pagekit/money";
import { liveMode, walletSnapshot, walletAddresses, saveWalletAddresses } from "../live";
import { useStore } from "../store";
import { useAdvanced } from "../uiMode";
import type { Chain, WalletAccount, WalletKind, WalletsSnapshot, WatchedAddress } from "../types";

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

const KIND_WORD: Record<WalletKind, string> = {
  broker: "Broker",
  exchange: "Exchange",
  onchain: "Crypto address",
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

  const subtitle = advanced
    ? "Broker, exchanges and watch-only addresses on one balance sheet."
    : "Your real accounts in one place: what is in them, and whether Pythia could trade there.";

  if (mode === "none") {
    return (
      <Page title="Money" subtitle={subtitle}>
        <KeyStats
          items={[
            {
              label: "Practice balance",
              value: money(portfolio.equity),
              sub: "Fake money. This is the only balance the browser version has.",
              help: "The practice account's value. No real money is involved.",
            },
          ]}
        />
        <Card>
          <Nothing icon={Wallet} title="Real account balances need the desktop app">
            Reading a broker, an exchange or a crypto address needs either the desktop app (keys stay in your computer's
            keychain) or a connected server. This browser version never sees a real account.
          </Nothing>
        </Card>
      </Page>
    );
  }

  const accounts = snap?.accounts ?? [];
  const counts = walletCounts(accounts);

  return (
    <Page
      title="Money"
      subtitle={subtitle}
      right={
        <Button variant="secondary" size="sm" icon={RefreshCw} disabled={busy} onClick={() => void refresh()}>
          {busy ? "Reading" : "Refresh"}
        </Button>
      }
    >
      {snap ? (
        <KeyStats
          items={[
            {
              label: "Total across your accounts",
              value: money(snap.usdTotal),
              sub: (
                <>
                  {plural(snap.accounts.length, "account")}
                  {snap.updatedAt > 0 && `, read at ${new Date(snap.updatedAt).toLocaleTimeString()}`}
                </>
              ),
              help: "Every connected broker, exchange and watched address added up in dollars. Coins without a dollar price are left out.",
            },
            {
              label: "Pythia can trade",
              value: String(counts.canTrade),
              sub: counts.canTrade === 1 ? "account with a trading key" : "accounts with a trading key",
              help: "Accounts where Pythia holds a key that can place orders. You can switch the key off at any time.",
            },
            {
              label: "Watch only",
              value: String(counts.watchOnly),
              sub: "it sees the balance, cannot move it",
              help: "Accounts Pythia can read but not trade in.",
            },
          ]}
        />
      ) : (
        <Card label="Total across your accounts">
          {busy ? (
            <LoadingRows rows={1} label="Reading balances" />
          ) : (
            <p className="text-[15px] text-muted">Not read yet. Press Refresh to read the balances.</p>
          )}
        </Card>
      )}

      <Notice tone="info" icon={ShieldCheck} title={advanced ? "Read-only, and self-custody stays self-custody" : "Pythia can look, not take"}>
        {advanced ? (
          <>
            Pythia never asks for a seed phrase or a wallet private key. On-chain wallets are watched by public address:
            it can see them, it cannot move them. Trading happens only at venues where you hold a{" "}
            <b className="text-ink">revocable API key</b>, so a compromised Pythia costs you a key rotation, not your coins.
          </>
        ) : (
          <>
            It never asks for a seed phrase or a wallet private key. Crypto wallets are watched by their public address,
            which lets it see a balance but never move it. Where it can trade, it uses a key you can switch off at any time.
          </>
        )}
      </Notice>

      {err && (
        <Notice tone="danger" icon={TriangleAlert} title="Could not read the balances">
          {err}
        </Notice>
      )}

      {snap?.unpriced.length ? (
        <Notice tone="warning" title="Some coins have no dollar price">
          {snap.unpriced.join(", ")} {snap.unpriced.length === 1 ? "is" : "are"} held but left out of the total rather than
          counted as zero.
        </Notice>
      ) : null}

      {snap && (
        <Section title="Accounts" hint="Each account with what it holds. Tap Refresh above to read them again.">
          {accounts.length === 0 ? (
            <Nothing icon={Wallet} title="Nothing connected yet">
              Add broker or exchange keys in Settings{mode === "native" ? ", or watch a crypto address below" : ""}. Until
              then Pythia only trades with practice money.
            </Nothing>
          ) : (
            <List>
              {accounts.map((a) => (
                <AccountRow key={a.id} account={a} />
              ))}
            </List>
          )}
        </Section>
      )}

      {mode === "native" && <AddressBook onSaved={() => void refresh()} />}
    </Page>
  );
}

function AccountRow({ account }: { account: WalletAccount }) {
  const Icon = KIND_ICON[account.kind];
  const held = heldBalances(account.balances);
  return (
    <div className="pb-3">
      <ListRow
        icon={Icon}
        title={account.label}
        subtitle={
          <span className="flex flex-wrap items-center gap-1.5">
            <span>
              {KIND_WORD[account.kind]} · {account.provider}
            </span>
            {account.canTrade ? (
              <Badge tone="good" title="Pythia holds a key that can place orders here">
                Can trade
              </Badge>
            ) : (
              <Badge tone="neutral" title="Pythia can see the balance but cannot move anything">
                Watch only
              </Badge>
            )}
          </span>
        }
        right={money(account.usdTotal)}
      />
      {account.error ? (
        <p className="break-words pl-[52px] text-[13px] text-down">{account.error}</p>
      ) : held.length === 0 ? (
        <p className="pl-[52px] text-[13px] text-muted">Empty: no balance in this account.</p>
      ) : (
        <ul className="ml-[52px] divide-y divide-line rounded-control bg-surface-2 px-3">
          {held.map((b) => (
            <li key={b.asset} className="flex items-start justify-between gap-3 py-2">
              <div className="min-w-0">
                <div className="break-all text-[15px] font-semibold text-ink">{b.asset}</div>
                <div className="tabular text-[13px] text-muted">
                  <Term>Free</Term> {trimQty(b.free)} · <Term>Total</Term> {trimQty(b.total)}
                </div>
              </div>
              <div className="tabular shrink-0 text-right text-[15px] font-semibold text-ink">
                {b.usdValue === undefined ? (
                  <span className="text-[13px] font-normal text-muted" title="No dollar price available">
                    No price
                  </span>
                ) : (
                  money(b.usdValue)
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Desktop-only editor for watch-only addresses. */
function AddressBook({ onSaved }: { onSaved: () => void }) {
  const [list, setList] = useState<WatchedAddress[]>([]);
  const [chain, setChain] = useState<Chain>("ethereum");
  const [address, setAddress] = useState("");
  const [label, setLabel] = useState("");
  const [err, setErr] = useState("");
  const [undoNotice, offerUndo] = useUndoNote();

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
    <Section
      title="Watch an address"
      help="A public address only shows a balance. It cannot be used to spend."
      hint={
        <>
          Paste a <b className="text-ink">public address</b>. Pythia reads the chain's own coin balance and nothing else:
          no key, no signing, no way to spend.
        </>
      }
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Network">
          <select value={chain} onChange={(e) => setChain(e.target.value as Chain)} className={inputCls}>
            {CHAINS.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label} ({c.asset})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Name (optional)">
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. cold wallet" className={inputCls} />
        </Field>
        <Field label="Public address" className="sm:col-span-2">
          <input
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="0x… / bc1… / base58"
            spellCheck={false}
            autoComplete="off"
            className={inputCls}
          />
        </Field>
      </div>
      <div className="mt-3">
        <Button variant="primary" icon={Plus} onClick={() => void add()} disabled={!address.trim()}>
          Add
        </Button>
      </div>
      {err && (
        <Notice tone="danger" className="mt-3">
          {err}
        </Notice>
      )}
      {undoNotice && <div className="mt-3">{undoNotice}</div>}

      <div className="mt-4 border-t border-line pt-1">
        {list.length === 0 ? (
          <p className="py-3 text-[13px] text-muted">No addresses watched yet.</p>
        ) : (
          <List>
            {list.map((w, i) => (
              <div key={`${w.chain}:${w.address}`} className="flex items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <div className="truncate text-[15px] font-semibold text-ink">{w.label || shortAddress(w.address)}</div>
                  <div className="break-all text-[13px] text-muted">{w.address}</div>
                  <div className="text-[13px] text-muted">{CHAINS.find((c) => c.id === w.chain)?.label ?? w.chain}</div>
                </div>
                <Button
                  variant="secondary"
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
          </List>
        )}
      </div>
    </Section>
  );
}
