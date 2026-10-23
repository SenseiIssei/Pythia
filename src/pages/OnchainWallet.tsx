// The pieces of our own on-chain wallet, used by the Wallet tab (and a short
// summary on the Real money page): the owner's locked real-money Solana trader,
// run by the lab's service on the server once the owner arms it
// (docs/ONCHAIN-STAGE2.md). Where to send SOL (address and QR code, made here in
// the browser), what the wallet holds in dollars and euro with the 24 h change,
// whether it trades and why not, the owner's conversions between the allowed
// coins (ask for a quote, then confirm exactly that quote within its minute),
// every movement from the chain, and the kill switch. There is no withdraw or
// transfer: the owner withdraws with his own wallet and his backup.

import { useCallback, useEffect, useState } from "react";
import { ArrowDownLeft, ArrowRightLeft, ArrowUpRight, Check, ChevronRight, CircleSlash, ExternalLink, OctagonX, QrCode, Receipt } from "lucide-react";
import { Badge, Button, Card, Change, Field, List, ListRow, Notice, inputCls } from "../design";
import { ConfirmAction, LoadingRows, Nothing, Row, Section } from "../pagekit";
import { short } from "../pumpfunLive";
import { euro } from "../realMoney";
import { openPage } from "../navigate";
import {
  STATE_WORDS,
  allowedCoins,
  amountText,
  balanceMoney,
  canControlOnchain,
  change24h,
  checkConvert,
  gateReasons,
  historyAmounts,
  historyFee,
  historyPrice,
  historyTitle,
  onchainConfirm,
  onchainConvert,
  onchainKill,
  onchainLive,
  pollMs,
  secondsLeft,
  solscanTx,
  totalMoney,
  usdText,
  walletState,
  type ConvertInput,
  type HistoryKind,
  type OnchainConvert,
  type OnchainView,
} from "../onchainLive";
import { AddressQr, CopyAddress } from "./PumpfunWallet";

export const when = (ms: number | null | undefined) =>
  ms == null ? "" : new Date(ms).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));
const stateTone = (s: OnchainConvert["state"]) =>
  s === "filled" ? "good" : s === "failed" || s === "refused" ? "bad" : s === "expired" ? "neutral" : "warn";

/**
 * The wallet's view, read every 3 s while a conversion is on its way and every
 * 15 s otherwise, only while `active` (its page is shown). `offset` is the
 * server's clock minus this one, for the proposal's countdown.
 */
export function useOnchainLive(active: boolean) {
  const [v, setV] = useState<OnchainView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const load = useCallback(async () => {
    try {
      const nv = await onchainLive();
      setV(nv);
      setOffset(nv.nowMs - Date.now());
      setErr(null);
    } catch (e) {
      setErr(errText(e));
    }
  }, []);
  const every = pollMs(v);
  useEffect(() => {
    if (!active || !canControlOnchain()) return;
    void load();
    const id = window.setInterval(() => void load(), every);
    return () => window.clearInterval(id);
  }, [active, every, load]);
  return { v, err, offset, load };
}

/** A proposal's seconds left, ticking once a second while it shows. */
function useCountdown(c: OnchainConvert | null, offset: number): number | null {
  const [now, setNow] = useState(() => Date.now());
  const live = c?.state === "proposed";
  useEffect(() => {
    if (!live) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, [live]);
  return c ? secondsLeft(c, now + offset) : null;
}

/** Locked, Alpha or Test, as a badge for the page header. */
export function ModeBadge({ v }: { v: OnchainView }) {
  const st = walletState(v);
  return (
    <span
      role="status"
      title={st.words}
      data-mode={st.mode}
      className={`inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-full px-3 text-[13px] font-semibold ${
        st.mode === "alpha" ? "bg-warn/15 text-warn ring-1 ring-inset ring-warn/60" : st.mode === "test" ? "bg-up/10 text-up" : st.tone === "bad" ? "bg-down text-on-down" : "bg-surface-2 text-muted"
      }`}
    >
      {st.mode === "alpha" ? "Alpha" : st.mode === "test" ? "Test" : st.alpha ? "Alpha, locked" : "Locked"}
    </span>
  );
}

/** The gate's state in plain words and every reason it does not trade. */
export function GateState({ v }: { v: OnchainView }) {
  const st = walletState(v);
  const reasons = gateReasons(v);
  return (
    <Notice tone={st.tone === "good" ? "success" : st.tone === "bad" ? "danger" : st.tone === "warn" ? "warning" : "info"} title={st.label}>
      <p>{st.words}</p>
      {reasons.length > 0 && (
        <ul className="mt-1 list-disc pl-5">
          {reasons.slice(0, 10).map((g) => (
            <li key={g}>{g}</li>
          ))}
        </ul>
      )}
      {v.status?.ack?.mode && <p className="mt-1">Confirmation file: {v.status.ack.mode} mode{v.status.ack.expires ? `, until ${v.status.ack.expires}` : ""}.</p>}
    </Notice>
  );
}

/** What the wallet holds, coin by coin: amount, dollars, euro, the price's change over 24 hours. */
export function Assets({ v }: { v: OnchainView }) {
  const s = v.status;
  return (
    <Section title="Assets" hint="Read from the chain by the trader; dollars at Jupiter's prices, euro at Kraken's EUR/USD, the change of each price over 24 hours.">
      {s && s.balances.length > 0 ? (
        <List>
          {s.balances.map((b) => {
            const m = balanceMoney(b, v.eurUsd);
            const ch = change24h(v, b.coin);
            return (
              <ListRow
                key={b.coin}
                ticker={b.coin}
                title={b.symbol || b.coin}
                subtitle={`${amountText(b.amount)} ${b.symbol || b.coin}${b.priceUsd != null ? ` · ${usdText(b.priceUsd)}` : ""}`}
                right={usdText(m.usd)}
                rightSub={
                  <span className="inline-flex flex-wrap items-center justify-end gap-x-2">
                    {m.eur != null && <span className="text-muted">{euro(m.eur)}</span>}
                    {ch != null && <Change pct={ch * 100} tone={ch > 0 ? "up" : ch < 0 ? "down" : "flat"} size="sm" suffix="24 h" />}
                  </span>
                }
              />
            );
          })}
        </List>
      ) : (
        <p className="text-sm text-muted">{s ? "The wallet holds nothing yet." : "No balances until the trader runs."}</p>
      )}
      {s?.day && (
        <p className="mt-2 text-[12px] text-faint">
          Today: {s.day.pnlUsd == null ? "n/a" : `${s.day.pnlUsd >= 0 ? "+" : ""}${usdText(s.day.pnlUsd)}`}
          {s.day.swaps != null ? ` · ${s.day.swaps} swaps` : ""}
          {s.day.converts != null ? ` · ${s.day.converts} conversions (${usdText(s.day.convertUsd)})` : ""}
        </p>
      )}
    </Section>
  );
}

/** Where to send SOL: the address, its QR code and a copy button. */
export function Receive({ v }: { v: OnchainView }) {
  const s = v.status;
  const cap = s?.limits?.maxTotalUsd ?? s?.ack?.maxTotalUsd ?? s?.hard?.maxTotalUsd ?? null;
  return (
    <Section title="Receive" hint="Send SOL here from your own wallet or exchange. That is the only way money gets in.">
      {v.address ? (
        <div className="space-y-4">
          <p className="text-center text-[15px] font-semibold text-ink">Send SOL here</p>
          <AddressQr address={v.address} />
          <div className="break-all text-center font-code text-[13px] text-ink">{v.address}</div>
          <div className="flex justify-center">
            <CopyAddress address={v.address} />
          </div>
          <Notice tone="info" title="Send only what the trader may use">
            Send no more than {cap == null ? "the confirmation file's total budget" : usdText(cap)} plus 0.05 SOL for network fees.
          </Notice>
        </div>
      ) : (
        <Nothing icon={QrCode} title="No wallet yet">
          The owner makes the wallet on the server with the wallet tool (docs/ONCHAIN-STAGE2.md). Its public address shows up here.
        </Nothing>
      )}
    </Section>
  );
}

/** The conversion being worked on: waiting for the quote, the quote with its countdown and Confirm, or why it was refused. */
function Current({ c, offset, onDone }: { c: OnchainConvert; offset: number; onDone: () => void }) {
  const left = useCountdown(c, offset);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const confirm = async () => {
    setBusy(true);
    setErr(null);
    try {
      await onchainConfirm(c.id);
      onDone();
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(false);
    }
  };
  const what = `${amountText(c.amount)} ${c.from ?? "?"} to ${c.to ?? "?"}`;
  if (c.state === "waiting") return <Notice tone="info" title={`Asking for a quote: ${what}`}>The trader answers within a few seconds while it runs.</Notice>;
  if (c.state === "refused") return <Notice tone="danger" title={`Refused: ${what}`}>{c.why ?? "The trader gave no reason."}</Notice>;
  if (c.state === "confirmed") return <Notice tone="info" title={`Confirmed: ${what}`}>The trader checks the swap again, then sends it. The result shows in the history.</Notice>;
  if (c.state !== "proposed") return null;
  const over = left === 0;
  return <Quote c={c} left={left} over={over} err={err} busy={busy} onConfirm={() => void confirm()} />;
}

/** A quote's preview: what you get, the least you get, price impact, fee, cost and route, with Confirm while it is fresh. */
export function Quote({ c, left, over, err, busy, onConfirm }: { c: OnchainConvert; left: number | null; over: boolean; err: string | null; busy: boolean; onConfirm: () => void }) {
  const what = `${amountText(c.amount)} ${c.from ?? "?"} to ${c.to ?? "?"}`;
  return (
    <div className="space-y-3 rounded-xl border border-line p-3">
      <div className="flex items-center gap-2">
        <span className="text-[15px] font-semibold text-ink">Quote: {what}</span>
        <Badge tone={over ? "neutral" : "warn"}>{over ? "expired" : `${left ?? "?"} s left`}</Badge>
      </div>
      <div className="divide-y divide-line">
        <Row label="You get about" value={`${amountText(c.expectedOut)} ${c.to ?? ""}`} help="What the quote expects you to get." />
        <Row label="Minimum received" value={`${amountText(c.minOut)} ${c.to ?? ""}`} sub={c.slippageBps != null ? `slippage ${c.slippageBps} bps` : undefined} help="Less than this and the swap fails on chain instead of filling." />
        <Row label="Price impact" value={c.priceImpactPct == null ? "n/a" : `${(c.priceImpactPct * 100).toFixed(3)} %`} help="How much this swap moves the pools' price, from Jupiter." />
        <Row label="Network fee" value={c.feeSol == null ? "n/a" : `at most ${amountText(c.feeSol, 9)} SOL`} help="Base fee, priority fee at the unit cap and the Sender tip; usually less is paid." />
        <Row label="Cost" value={c.costBps == null ? "n/a" : `${c.costBps.toFixed(1)} bps`} sub={c.inUsd == null ? undefined : `on ${usdText(c.inUsd)}`} help="Price impact and fees against the mid price, in hundredths of a percent." />
        <Row label="Route" value={c.route.length ? c.route.join(", ") : "n/a"} help="The pools the swap goes through." />
      </div>
      {err && <Notice tone="danger">{err}</Notice>}
      <Button icon={Check} disabled={busy || over || !canControlOnchain()} onClick={onConfirm}>
        Confirm
      </Button>
    </div>
  );
}

/** Swap between the allowed coins: a quote, then the confirm of exactly that quote within its 60 seconds. */
export function Swap({ v, offset, onChanged }: { v: OnchainView; offset: number; onChanged: () => void }) {
  const coins = allowedCoins(v.status);
  const [input, setInput] = useState<ConvertInput>(() => ({ from: coins[1] ?? coins[0] ?? "", to: coins[0] ?? "", amount: "" }));
  const [asked, setAsked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const { ask, errors } = checkConvert(input, v);
  const current = v.converts.find((c) => c.id === asked) ?? v.converts.find((c) => c.state === "proposed" || c.state === "waiting") ?? null;
  const send = async () => {
    if (!ask) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await onchainConvert(ask);
      setAsked(r.id);
      setInput({ ...input, amount: "" });
      onChanged();
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(false);
    }
  };
  const max = v.status?.limits?.maxTradeUsd ?? null;
  const shownErrors = input.amount.trim() ? errors : errors.filter((e) => !e.startsWith("The amount"));
  return (
    <Section
      title="Swap"
      hint={`Swap between the allowed coins through the trader. Get a quote, then confirm it within its minute; nothing moves without the confirm.${max != null ? ` At most ${usdText(max)} a swap.` : ""}`}
    >
      {!v.running || !v.status ? (
        <p className="text-sm text-muted">Swaps need the trader running.</p>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="From">
              <select className={inputCls} value={input.from} onChange={(e) => setInput({ ...input, from: e.target.value })} aria-label="Swap from">
                <option value="">Choose</option>
                {coins.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </Field>
            <Field label="To">
              <select className={inputCls} value={input.to} onChange={(e) => setInput({ ...input, to: e.target.value })} aria-label="Swap to">
                <option value="">Choose</option>
                {coins.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </Field>
            <Field label={`Amount${input.from ? ` (${input.from})` : ""}`}>
              <input className={inputCls} inputMode="decimal" value={input.amount} onChange={(e) => setInput({ ...input, amount: e.target.value })} aria-label="Amount to swap" />
            </Field>
          </div>
          {shownErrors.length > 0 && (
            <ul className="list-disc pl-5 text-[13px] text-down" role="alert">
              {shownErrors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
          {err && <Notice tone="danger">{err}</Notice>}
          <Button icon={ArrowRightLeft} variant="secondary" disabled={busy || !ask || !canControlOnchain()} onClick={() => void send()}>
            Get quote
          </Button>
        </div>
      )}
      {current && (
        <div className="mt-4">
          <Current key={current.id} c={current} offset={offset} onDone={onChanged} />
        </div>
      )}
      {v.converts.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-1 text-[13px] font-semibold text-muted">Your newest swaps</h3>
          <List>
            {v.converts.map((c) => (
              <ListRow
                key={c.id}
                title={
                  <span className="flex items-center gap-2">
                    {`${amountText(c.amount)} ${c.from ?? "?"} to ${c.to ?? "?"}`}
                    <Badge tone={stateTone(c.state)}>{STATE_WORDS[c.state]}</Badge>
                  </span>
                }
                subtitle={[when(c.requestedMs ?? c.proposedMs), c.why, c.sig ? `tx ${short(c.sig)}` : null].filter(Boolean).join(" · ")}
                right={c.outAmount != null ? `${amountText(c.outAmount)} ${c.to ?? ""}` : c.expectedOut != null ? `~${amountText(c.expectedOut)} ${c.to ?? ""}` : ""}
                rightSub={c.costBps == null ? undefined : `${c.costBps.toFixed(1)} bps`}
              />
            ))}
          </List>
        </div>
      )}
    </Section>
  );
}

const KIND_ICON: Record<HistoryKind, typeof ArrowDownLeft> = {
  deposit: ArrowDownLeft,
  swap: ArrowRightLeft,
  sent: ArrowUpRight,
  failed: CircleSlash,
  other: Receipt,
};

/** Every movement of the wallet from the chain, newest first, each with its Solscan link. */
export function History({ v }: { v: OnchainView }) {
  return (
    <Section
      title="History"
      hint={`Every movement in and out of the wallet as the chain shows it: deposits, swaps with their price, fees, failed transactions.${v.historyMs ? ` Read ${when(v.historyMs)}.` : ""}`}
    >
      {v.history.length > 0 ? (
        <List>
          {v.history.map((e, i) => (
            <ListRow
              key={e.sig ?? i}
              icon={KIND_ICON[e.kind]}
              title={
                <span className="flex items-center gap-2" data-kind={e.kind}>
                  <span className="truncate">{historyTitle(e)}</span>
                  {!e.ok && <Badge tone="bad">failed</Badge>}
                  {e.sig && (
                    <a href={solscanTx(e.sig)} target="_blank" rel="noreferrer noopener" className="fl-focus shrink-0 text-muted hover:text-ink" aria-label="The transaction on Solscan">
                      <ExternalLink size={14} />
                    </a>
                  )}
                </span>
              }
              subtitle={[when(e.t), historyPrice(e), historyFee(e), e.err].filter(Boolean).join(" · ")}
              right={historyAmounts(e)[0] ?? ""}
              rightSub={historyAmounts(e).slice(1).join(" ") || undefined}
            />
          ))}
        </List>
      ) : (
        <p className="text-sm text-muted">{v.historyMs ? "No movement yet." : "The history job reads the chain every 5 minutes; nothing read yet."}</p>
      )}
    </Section>
  );
}

/** The trader's own ledger: every swap and conversion it made, with its book. */
export function Ledger({ v }: { v: OnchainView }) {
  if (v.trades.length === 0) return <p className="text-sm text-muted">No swap of the trader yet.</p>;
  return (
    <List>
      {v.trades.map((t, i) => (
        <ListRow
          key={`${t.t}-${t.sig ?? i}`}
          title={
            <span className="flex items-center gap-2">
              {`${t.from ?? "?"} to ${t.to ?? "?"}`}
              <Badge tone={t.status === "filled" ? "good" : "bad"}>{t.status ?? "?"}</Badge>
            </span>
          }
          subtitle={[when(t.t), t.kind === "convert" ? "conversion" : t.book, t.feeSol != null ? `fee ${amountText(t.feeSol, 6)} SOL` : null, t.why].filter(Boolean).join(" · ")}
          right={`${amountText(t.inAmount)} ${t.from ?? ""}`}
          rightSub={t.outAmount == null ? undefined : `${amountText(t.outAmount)} ${t.to ?? ""}${t.outUsd != null ? ` (${usdText(t.outUsd)})` : ""}`}
        />
      ))}
    </List>
  );
}

/** The kill switch: writes the kill file on the server; only deleting it there allows swaps again. */
export function KillSwitch({ v, onDone }: { v: OnchainView; onDone: () => void }) {
  const [msg, setMsg] = useState<string | null>(null);
  const kill = async () => {
    try {
      const k = await onchainKill();
      setMsg(k.already ? "The kill file was already there." : "Kill switch set. The trader makes no swap and no conversion.");
      onDone();
    } catch (e) {
      setMsg(errText(e));
    }
  };
  return (
    <Section title="Stop the on-chain trader" hint="The kill switch creates a file on the server: the trader makes no swap and no conversion. To allow trades again, delete reports/onchain_live/KILL on the server by hand; the app cannot undo it.">
      {v.killFile ? (
        <Notice tone="danger" title="Kill switch is on">Delete reports/onchain_live/KILL in the lab's data folder on the server to allow trades again.</Notice>
      ) : (
        <ConfirmAction
          icon={OctagonX}
          title="Stop the on-chain trader"
          confirmLabel="Stop trading now"
          question="This writes the kill file on the server. The trader makes no swap and no conversion. Only deleting the file on the server allows trades again."
          onConfirm={() => void kill()}
        >
          Stop trading now
        </ConfirmAction>
      )}
      {msg && <p className="mt-3 text-sm text-muted">{msg}</p>}
    </Section>
  );
}

/** The on-chain wallet in a few lines for the Real money page, with the way to the Wallet tab. */
export function OnchainSummary({ v, err }: { v: OnchainView | null; err: string | null }) {
  const go = (
    <button type="button" onClick={() => openPage("wallet")} className="inline-flex items-center gap-1 text-[13px] font-semibold text-accent hover:underline">
      Assets, swap, history <ChevronRight size={14} aria-hidden />
    </button>
  );
  if (!canControlOnchain()) return <p className="px-1 text-sm text-muted">The on-chain wallet needs the connected backend on the server.</p>;
  if (err && !v) return <Notice tone="warning" title="Could not read the on-chain trader">{err}</Notice>;
  if (!v) return <LoadingRows rows={2} label="Reading the on-chain trader" />;
  const st = walletState(v);
  const total = totalMoney(v.status, v.eurUsd);
  return (
    <Card label="On-chain wallet" right={go} title={<span className="flex items-center gap-2">Our wallet <ModeBadge v={v} /></span>}>
      <div className="divide-y divide-line">
        <Row label="Worth" value={usdText(total.usd)} valueSub={total.eur == null ? undefined : euro(total.eur)} help="Everything in the wallet." />
        <Row label="State" value={st.label} sub={st.words} help="Locked, Alpha or Test, as the trader on the server reports it." />
      </div>
    </Card>
  );
}
