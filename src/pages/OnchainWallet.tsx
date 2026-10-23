// The on-chain wallet on the Real money page: the owner's locked real-money
// Solana trader, run by the lab's service on the server once the owner arms it
// (docs/ONCHAIN-STAGE2.md). It shows where to send SOL (address and QR code,
// made here in the browser), what the wallet holds in dollars and euro, whether
// it trades and why not, the owner's conversions between the allowed coins
// (ask for a quote, then confirm exactly that quote within its minute), every
// swap, and the kill switch. There is no withdraw or transfer: the owner
// withdraws with his own wallet and his backup.

import { useCallback, useEffect, useState } from "react";
import { ArrowRightLeft, Check, ExternalLink, OctagonX, QrCode } from "lucide-react";
import { Badge, Button, Field, List, ListRow, Notice, inputCls } from "../design";
import { ConfirmAction, LoadingRows, More, Nothing, Row, Section } from "../pagekit";
import { short } from "../pumpfunLive";
import { euro } from "../realMoney";
import {
  STATE_WORDS,
  allowedCoins,
  amountText,
  balanceMoney,
  canControlOnchain,
  checkConvert,
  gateReasons,
  onOff,
  onchainConfirm,
  onchainConvert,
  onchainKill,
  onchainLive,
  pollMs,
  secondsLeft,
  solscanTx,
  totalMoney,
  usdText,
  type ConvertInput,
  type OnchainConvert,
  type OnchainView,
} from "../onchainLive";
import { AddressQr, CopyAddress } from "./PumpfunWallet";

const when = (ms: number | null | undefined) =>
  ms == null ? "" : new Date(ms).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));
const stateTone = (s: OnchainConvert["state"]) =>
  s === "filled" ? "good" : s === "failed" || s === "refused" ? "bad" : s === "expired" ? "neutral" : "warn";

/**
 * The section's view, read every 3 s while a conversion is on its way and every
 * 15 s otherwise, only while `active` (the Real money page is shown). `offset` is
 * the server's clock minus this one, for the proposal's countdown.
 */
function useOnchainLive(active: boolean) {
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

function Balances({ v }: { v: OnchainView }) {
  const s = v.status;
  const total = totalMoney(s, v.eurUsd);
  return (
    <Section title="On-chain balances" hint="What the wallet holds, read from the chain by the trader; dollars at its prices, euro at Kraken's EUR/USD.">
      {s && s.balances.length > 0 ? (
        <div className="divide-y divide-line">
          {s.balances.map((b) => {
            const m = balanceMoney(b, v.eurUsd);
            return (
              <Row
                key={b.coin}
                label={b.symbol || b.coin}
                sub={`${amountText(b.amount)} ${b.symbol || b.coin}${b.priceUsd != null ? ` at ${usdText(b.priceUsd)}` : ""}`}
                value={usdText(m.usd)}
                valueSub={m.eur == null ? undefined : euro(m.eur)}
                help="The amount on chain and what it is worth."
              />
            );
          })}
          <Row label="Total" value={usdText(total.usd)} valueSub={total.eur == null ? undefined : euro(total.eur)} help="Everything in the wallet." />
        </div>
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

function Fund({ v }: { v: OnchainView }) {
  const s = v.status;
  const cap = s?.limits?.maxTotalUsd ?? s?.ack?.maxTotalUsd ?? s?.hard?.maxTotalUsd ?? null;
  return (
    <Section title="Fund the on-chain wallet" hint="Send SOL from your own wallet or exchange to this address. That is the only way money gets in.">
      {v.address ? (
        <div className="space-y-4">
          <AddressQr address={v.address} />
          <div className="break-all text-center font-code text-[13px] text-ink">{v.address}</div>
          <div className="flex justify-center">
            <CopyAddress address={v.address} />
          </div>
          <Notice tone="info" title="Send only what the trader may use">
            Send no more than {cap == null ? "the confirmation file's total budget" : usdText(cap)} plus 0.05 SOL for network fees. Pythia has no withdraw function: to take money out, import your backup into your own wallet and send it from there.
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
  if (c.state === "confirmed") return <Notice tone="info" title={`Confirmed: ${what}`}>The trader checks the swap again, then sends it. The result shows below.</Notice>;
  if (c.state !== "proposed") return null;
  const over = left === 0;
  return (
    <div className="space-y-3 rounded-xl border border-line p-3">
      <div className="flex items-center gap-2">
        <span className="text-[15px] font-semibold text-ink">Quote: {what}</span>
        <Badge tone={over ? "neutral" : "warn"}>{over ? "expired" : `${left ?? "?"} s left`}</Badge>
      </div>
      <div className="divide-y divide-line">
        <Row label="Expected out" value={`${amountText(c.expectedOut)} ${c.to ?? ""}`} help="What the quote expects you to get." />
        <Row label="Minimum out" value={`${amountText(c.minOut)} ${c.to ?? ""}`} help="Less than this and the swap fails on chain instead of filling." />
        <Row label="Cost" value={c.costBps == null ? "n/a" : `${c.costBps.toFixed(1)} bps`} sub={c.inUsd == null ? undefined : `on ${usdText(c.inUsd)}`} help="Price impact and fees against the mid price, in hundredths of a percent." />
        <Row label="Route" value={c.route.length ? c.route.join(", ") : "n/a"} help="The pools the swap goes through." />
      </div>
      {err && <Notice tone="danger">{err}</Notice>}
      <Button icon={Check} disabled={busy || over || !canControlOnchain()} onClick={() => void confirm()}>
        Confirm
      </Button>
    </div>
  );
}

function Convert({ v, offset, onChanged }: { v: OnchainView; offset: number; onChanged: () => void }) {
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
      title="Convert"
      hint={`Swap between the allowed coins through the trader. Get a quote, then confirm it within its minute; nothing moves without the confirm.${max != null ? ` At most ${usdText(max)} a trade.` : ""}`}
    >
      {!v.running || !v.status ? (
        <p className="text-sm text-muted">Conversions need the trader running.</p>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="From">
              <select className={inputCls} value={input.from} onChange={(e) => setInput({ ...input, from: e.target.value })} aria-label="Convert from">
                <option value="">Choose</option>
                {coins.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </Field>
            <Field label="To">
              <select className={inputCls} value={input.to} onChange={(e) => setInput({ ...input, to: e.target.value })} aria-label="Convert to">
                <option value="">Choose</option>
                {coins.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </Field>
            <Field label={`Amount${input.from ? ` (${input.from})` : ""}`}>
              <input className={inputCls} inputMode="decimal" value={input.amount} onChange={(e) => setInput({ ...input, amount: e.target.value })} aria-label="Amount to convert" />
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
    </Section>
  );
}

function Trades({ v }: { v: OnchainView }) {
  return (
    <Section title="On-chain trades" hint="Every swap of the trader and every conversion, newest first.">
      {v.trades.length > 0 ? (
        <List>
          {v.trades.map((t, i) => (
            <ListRow
              key={`${t.t}-${t.sig ?? i}`}
              title={
                <span className="flex items-center gap-2">
                  {`${t.from ?? "?"} to ${t.to ?? "?"}`}
                  <Badge tone={t.status === "filled" ? "good" : "bad"}>{t.status ?? "?"}</Badge>
                  {t.sig && (
                    <a href={solscanTx(t.sig)} target="_blank" rel="noreferrer noopener" className="fl-focus text-muted hover:text-ink" aria-label="The transaction on Solscan">
                      <ExternalLink size={14} />
                    </a>
                  )}
                </span>
              }
              subtitle={[when(t.t), t.kind === "convert" ? "conversion" : t.book, t.feeSol != null ? `fee ${amountText(t.feeSol, 6)} SOL` : null, t.why]
                .filter(Boolean)
                .join(" · ")}
              right={`${amountText(t.inAmount)} ${t.from ?? ""}`}
              rightSub={t.outAmount == null ? undefined : `${amountText(t.outAmount)} ${t.to ?? ""}${t.outUsd != null ? ` (${usdText(t.outUsd)})` : ""}`}
            />
          ))}
        </List>
      ) : (
        <p className="text-sm text-muted">No on-chain trade yet.</p>
      )}
    </Section>
  );
}

function Conversions({ v }: { v: OnchainView }) {
  return (
    <Section title="Conversions" hint="Your newest conversions and what became of each.">
      {v.converts.length > 0 ? (
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
      ) : (
        <p className="text-sm text-muted">No conversion yet.</p>
      )}
    </Section>
  );
}

/** The on-chain wallet's section of the Real money page. `active` false stops reading (the page is not shown). */
export function OnchainWallet({ active }: { active: boolean }) {
  const { v, err, offset, load } = useOnchainLive(active);
  const [killMsg, setKillMsg] = useState<string | null>(null);

  if (!canControlOnchain()) return <p className="px-1 text-sm text-muted">The on-chain wallet needs the connected backend on the server.</p>;
  if (err && !v) return <Notice tone="warning" title="Could not read the on-chain trader">{err}</Notice>;
  if (!v) return <LoadingRows rows={3} label="Reading the on-chain trader" />;

  const st = onOff(v);
  const reasons = gateReasons(v);
  const kill = async () => {
    try {
      const k = await onchainKill();
      setKillMsg(k.already ? "The kill file was already there." : "Kill switch set. The trader makes no swap and no conversion.");
      void load();
    } catch (e) {
      setKillMsg(errText(e));
    }
  };
  return (
    <>
      <Notice tone={st.level === "ok" ? "success" : st.level === "bad" ? "danger" : st.level === "warn" ? "warning" : "info"} title={st.label}>
        {reasons.length > 0 && (
          <ul className="list-disc pl-5">
            {reasons.slice(0, 10).map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        )}
        {v.status?.ack?.mode && <p className="mt-1">Confirmation file: {v.status.ack.mode} mode{v.status.ack.expires ? `, until ${v.status.ack.expires}` : ""}.</p>}
      </Notice>

      <Balances v={v} />
      <Fund v={v} />
      <Convert v={v} offset={offset} onChanged={() => void load()} />
      <Trades v={v} />
      <Conversions v={v} />

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
        {killMsg && <p className="mt-3 text-sm text-muted">{killMsg}</p>}
      </Section>

      <More title="How the on-chain wallet works">
        <div className="space-y-2 text-sm leading-relaxed text-muted">
          <p>The trader is locked until the owner arms it on the server with a confirmation file (docs/ONCHAIN-STAGE2.md). It only swaps between the allowed coins, within the file's limits and the caps in its code.</p>
          <p>A conversion is two steps: you ask for a quote, the trader answers with the expected and minimum amounts; only your confirm within its minute lets it send exactly that swap. Pythia never signs anything in the app.</p>
          {v.status?.simulate?.t != null && <p>Last dry run (simulation, nothing sent): {when(v.status.simulate.t)}, {v.status.simulate.ok ? "ok" : "failed"}.</p>}
          {v.status?.reconcile?.t != null && <p>Last check of the books against the chain: {when(v.status.reconcile.t)}, {v.status.reconcile.ok ? "matching" : `differences: ${v.status.reconcile.diffs.join("; ")}`}.</p>}
        </div>
      </More>
    </>
  );
}
