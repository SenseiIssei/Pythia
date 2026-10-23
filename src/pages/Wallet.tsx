// The Wallet tab: everything about our own wallets in one place, laid out like
// a wallet app. The on-chain wallet first (its worth in dollars and euro, the
// value over time, the coins with their 24 h change, the deposit address with QR
// code, the gate's state in plain words: locked, alpha or test, the Master panel
// with the share of the wallet, Stop and Start), then swap (the conversion flow
// with its quote preview and 60 s confirm), the history read from the chain, the
// kill switch, and the pump.fun bot's wallet as a second card (read only) with
// its own Master panel. There is no send-out button: Pythia never moves money
// out of a wallet; the page says how to withdraw. Opens on its own with
// `?page=wallet&embed=1` (the owner's DevPanel).

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowDownLeft, ArrowRightLeft, ExternalLink, History as HistoryIcon, QrCode } from "lucide-react";
import { AreaChart, BigNumber, Card, Change, Notice, Page } from "../design";
import { LoadingRows, More, Row, Section } from "../pagekit";
import { usePageVisible } from "../pageVisible";
import { openPage } from "../navigate";
import { currentDeepLink, pageQuery } from "../deepLink";
import { euro } from "../realMoney";
import { canControl, pumpfunLive, short, sol, type PumpfunView } from "../pumpfunLive";
import { canControlOnchain, solscanAccount, totalChange24h, totalMoney, usdText, valueLine, walletState, type OnchainView } from "../onchainLive";
import { Assets, GateState, History, KillSwitch, Ledger, ModeBadge, Receive, Swap, useOnchainLive, when } from "./OnchainWallet";
import { CopyAddress } from "./PumpfunWallet";
import { OnchainMaster, PumpfunMaster } from "../components/MasterPanel";

const PF_POLL_MS = 30_000;

/** The pump.fun bot's view, read every 30 s while the page is shown (its own page keeps the live socket). */
function usePumpfunWallet(active: boolean) {
  const [v, setV] = useState<PumpfunView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(
    () =>
      pumpfunLive()
        .then((nv) => {
          setV(nv);
          setErr(null);
        })
        .catch((e) => setErr(e instanceof Error ? e.message : String(e))),
    [],
  );
  useEffect(() => {
    if (!active || !canControl()) return;
    void load();
    const id = window.setInterval(() => void load(), PF_POLL_MS);
    return () => window.clearInterval(id);
  }, [active, load]);
  return { v, err, load };
}

/** The worth, its change over 24 hours, the value over time, and the shortcuts. */
function Overview({ v }: { v: OnchainView }) {
  const total = totalMoney(v.status, v.eurUsd);
  const line = useMemo(() => valueLine(v), [v]);
  const [at, setAt] = useState<number | null>(null);
  const ch = totalChange24h(v);
  const shownUsd = at == null ? total.usd : line[at]?.usd ?? total.usd;
  const shownEur = at == null ? total.eur : shownUsd != null && v.eurUsd ? shownUsd / v.eurUsd.price : null;
  const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  return (
    <Card label="Our on-chain wallet">
      <BigNumber
        label={at == null ? "Worth now" : `On ${when(line[at].t)}`}
        value={shownEur != null ? euro(shownEur) : usdText(shownUsd)}
        sub={
          <span className="inline-flex flex-wrap items-center gap-x-3 text-[13px] text-muted">
            {shownEur != null && <span className="tabular">{usdText(shownUsd)}</span>}
            {at == null && ch != null && <Change usd={ch} tone={ch > 0 ? "up" : ch < 0 ? "down" : "flat"} size="sm" suffix="24 h" />}
          </span>
        }
      />
      <div className="mt-3">
        <AreaChart
          data={line.map((p) => p.usd)}
          height={160}
          label={`The wallet's worth in US dollars over time, now ${usdText(total.usd)}`}
          onScrub={(x) => setAt(x ? x.index : null)}
          empty="The line starts once the trader has run for a while (a point every 15 minutes)."
        />
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2">
        {[
          { id: "wallet-receive-section", label: "Receive", Icon: ArrowDownLeft },
          { id: "wallet-swap-section", label: "Swap", Icon: ArrowRightLeft },
          { id: "wallet-history-section", label: "History", Icon: HistoryIcon },
        ].map(({ id, label, Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => jump(id)}
            className="flex flex-col items-center gap-1 rounded-control bg-surface-2 py-2.5 text-[13px] font-semibold text-ink transition-colors hover:bg-line"
          >
            <Icon size={18} aria-hidden />
            {label}
          </button>
        ))}
      </div>
      {v.eurUsd && <p className="mt-2 text-[12px] text-faint">1 EUR = {v.eurUsd.price.toFixed(4)} USD</p>}
    </Card>
  );
}

/** The pump.fun bot's wallet, read only: address, SOL balance, the way to its page. */
export function PumpfunCard({ v, err, embedded }: { v: PumpfunView | null; err: string | null; embedded: boolean }) {
  const addr = v?.status?.address ?? v?.address ?? null;
  const bal = v?.status?.balanceSol ?? null;
  const link = embedded ? (
    <a href={`${typeof window === "undefined" ? "" : window.location.pathname}${pageQuery("pumpfun")}`} target="_blank" rel="noreferrer noopener" className="text-[13px] font-semibold text-accent hover:underline">
      Its page
    </a>
  ) : (
    <button type="button" onClick={() => openPage("pumpfun")} className="text-[13px] font-semibold text-accent hover:underline">
      Its page
    </button>
  );
  return (
    <Card title="pump.fun bot's wallet" right={link} label="The pump.fun bot's wallet">
      {!v ? (
        <p className="text-sm text-muted">{err ?? "Reading the pump.fun live service."}</p>
      ) : (
        <div className="divide-y divide-line">
          <Row
            label="Address"
            value={addr ? short(addr) : "none yet"}
            sub={addr ? <a href={solscanAccount(addr)} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 hover:text-ink">On Solscan <ExternalLink size={12} aria-hidden /></a> : undefined}
            help="The bot's own wallet, separate from ours."
          />
          <Row
            label="Balance"
            value={sol(bal)}
            valueSub={bal != null && v.solEur ? euro(bal * v.solEur.price) : undefined}
            help="SOL in the bot's wallet, from its live service."
          />
          {addr && (
            <div className="pt-3">
              <CopyAddress address={addr} />
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

/** Everything below the header, given what was read (rendered by tests without a server). */
export function WalletBody({
  v,
  offset,
  onChanged,
  pf,
  pfErr,
  embedded,
  onPfChanged,
}: {
  v: OnchainView;
  offset: number;
  onChanged: () => void;
  pf: PumpfunView | null;
  pfErr: string | null;
  embedded: boolean;
  onPfChanged?: () => void;
}) {
  const st = walletState(v);
  return (
    <>
      {st.mode === "alpha" && (
        <Notice tone="warning" title="Alpha phase">
          Books trade small real money without the proof, to train and measure our own models. Every swap posts a card to Telegram and Discord.
        </Notice>
      )}
      <Overview v={v} />
      <GateState v={v} />
      <OnchainMaster v={v} onDone={onChanged} />
      <Assets v={v} />
      <div id="wallet-receive-section">
        <Receive v={v} />
      </div>
      <div id="wallet-swap-section">
        <Swap v={v} offset={offset} onChanged={onChanged} />
      </div>
      <div id="wallet-history-section">
        <History v={v} />
      </div>
      <PumpfunCard v={pf} err={pfErr} embedded={embedded} />
      {pf && <PumpfunMaster v={pf} onDone={() => onPfChanged?.()} />}
      <KillSwitch v={v} onDone={onChanged} />
      <Section title="How to withdraw">
        <div className="space-y-2 text-sm leading-relaxed text-muted">
          <p>There is no send-out button: Pythia never moves money out of a wallet, and its trader cannot (the guard knows no transfer).</p>
          <p>To take money out: stop the trader (the kill switch above), import the wallet's backup into Phantom or another wallet of your own, and send from there.</p>
        </div>
      </Section>
      <More title="The trader's ledger">
        <Ledger v={v} />
      </More>
      <More title="How the on-chain wallet works">
        <div className="space-y-2 text-sm leading-relaxed text-muted">
          <p>The trader is locked until the owner arms it on the server with a confirmation file (docs/ONCHAIN-STAGE2.md). It only swaps between the allowed coins, within the file's limits and the caps in its code. In the Alpha phase the caps are lower: at most 25 USD a swap, 100 USD in the wallet, 25 USD loss a day.</p>
          <p>A swap is two steps: you ask for a quote, the trader answers with the expected and minimum amounts; only your confirm within its minute lets it send exactly that swap. Pythia never signs anything in the app.</p>
          {v.status?.simulate?.t != null && <p>Last dry run (simulation, nothing sent): {when(v.status.simulate.t)}, {v.status.simulate.ok ? "ok" : "failed"}.</p>}
          {v.status?.reconcile?.t != null && <p>Last check of the books against the chain: {when(v.status.reconcile.t)}, {v.status.reconcile.ok ? "matching" : `differences: ${v.status.reconcile.diffs.join("; ")}`}.</p>}
        </div>
      </More>
    </>
  );
}

export function Wallet() {
  const ref = useRef<HTMLDivElement>(null);
  const shown = usePageVisible(ref);
  const { v, err, offset, load } = useOnchainLive(shown);
  const pf = usePumpfunWallet(shown);
  const embedded = useMemo(() => currentDeepLink().embed, []);
  return (
    <div ref={ref}>
      <Page
        wide
        title="Wallet"
        subtitle="Our own Solana wallet: what it holds, every movement, swaps. Pythia never sends money out of a wallet."
        right={v ? <ModeBadge v={v} /> : undefined}
      >
        {!canControlOnchain() ? (
          <Notice tone="info" title="Needs the server" icon={QrCode}>
            The wallet is read from the connected backend on the server.
          </Notice>
        ) : err && !v ? (
          <Notice tone="warning" title="Could not read the on-chain trader">{err}</Notice>
        ) : !v ? (
          <LoadingRows rows={4} label="Reading the on-chain wallet" />
        ) : (
          <WalletBody v={v} offset={offset} onChanged={() => void load()} pf={pf.v} pfErr={pf.err} embedded={embedded} onPfChanged={() => void pf.load()} />
        )}
      </Page>
    </div>
  );
}
