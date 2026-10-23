// The Master panel of a live bot (the pump.fun page and the Wallet page): the
// share of the wallet the bot may use, Stop and Start, with "limits: wallet" or
// "limits: fixed" said plainly. Stop takes effect at once and asks nothing;
// Start and a share raised above 50 % ask first. The kill switch stays a
// separate emergency stop on its own section. Logic in masterControl.ts.

import { useState, type ReactNode } from "react";
import { Pause, Play, RotateCcw } from "lucide-react";
import { Badge, Button, Field, Notice, inputCls } from "../design";
import { ConfirmAction, Row, Section } from "../pagekit";
import {
  SHARE_BUTTONS,
  confirmQuestion,
  hasOverride,
  isPaused,
  limitsKind,
  limitsText,
  lowText,
  needsConfirm,
  parseShare,
  patchOf,
  pausedText,
  shareRefusal,
  shareSourceText,
  shareText,
  type Bot,
  type MasterAction,
} from "../masterControl";
import { canControl, pumpfunControl, sol, type ControlFile, type ControlPatch, type LimitsKind, type LowFunds, type PumpfunView, type StatusControl } from "../pumpfunLive";
import { canControlOnchain, onchainControl, usdText, type OnchainView } from "../onchainLive";

/** The wallet is the limit: the rows that have no number then. */
export const WALLET_LIMIT = "none (the wallet is the limit)";

export interface MasterProps {
  bot: Bot;
  control: StatusControl | null;
  file: ControlFile | null;
  kind: LimitsKind;
  ackShare: number | null;
  low: LowFunds | null;
  /** Server mode: the panel acts; else it only shows. */
  can: boolean;
  /** The effective stake or caps, under the share. */
  rows?: ReactNode;
}

export interface MasterViewProps extends MasterProps {
  custom: string;
  onCustom: (text: string) => void;
  busy: boolean;
  msg: string | null;
  err: string | null;
  send: (p: ControlPatch) => void;
}

const STOP_WORDS: Record<Bot, string> = {
  pumpfun: "Stop: no new buys from now; open positions are still sold by their exits.",
  onchain: "Stop: no new book trades from now; what the wallet holds stays held unless you convert it.",
};

/** The panel as it shows, from its props only (no state: the tests read it as a tree). */
export function MasterView(p: MasterViewProps) {
  const { bot, control, file, kind, ackShare, can, busy } = p;
  const current = control?.share ?? file?.share ?? null;
  const paused = isPaused(control, file);
  const pausedLine = pausedText(control, file);
  const requested = file?.share ?? control?.requestedShare ?? null;
  const low = lowText(p.low);
  const parsed = parseShare(p.custom);
  const customRefusal = parsed.share != null ? shareRefusal(parsed.share, bot, kind, ackShare) : null;
  const refusals = SHARE_BUTTONS.map((x) => shareRefusal(x, bot, kind, ackShare));
  const hint = refusals.find((r) => r != null) ?? null;
  const off = !can || busy;
  const act = (a: MasterAction) => () => p.send(patchOf(a));
  const shareButton = (a: MasterAction & { kind: "share" }, label: string, disabled: boolean, variant: "primary" | "secondary") =>
    needsConfirm(a, current) ? (
      <ConfirmAction key={label} size="sm" danger={false} variant={variant} disabled={disabled} title={`Raise the share to ${shareText(a.share)}?`} confirmLabel={`Set ${shareText(a.share)}`} question={confirmQuestion(a, bot)} onConfirm={act(a)}>
        {label}
      </ConfirmAction>
    ) : (
      <Button key={label} size="sm" variant={variant} disabled={disabled} onClick={act(a)}>
        {label}
      </Button>
    );
  const start: MasterAction = { kind: "start" };
  return (
    <Section
      title="Master"
      right={
        <Badge tone={kind === "wallet" ? "accent" : "neutral"} title={kind === "wallet" ? "The confirmation file says limits=wallet: the stake and the caps follow the wallet." : "The confirmation file's fixed amounts and the code's caps apply."}>
          {limitsText(kind)}
        </Badge>
      }
      hint={`${STOP_WORDS[bot]} Start lets it trade again. The kill switch stays the separate emergency stop.`}
    >
      <div className="divide-y divide-line">
        <Row
          label={bot === "pumpfun" ? "Share per trade" : "Share of the wallet"}
          value={current != null ? shareText(current) : bot === "onchain" && control?.bookUsd != null ? `${usdText(control.bookUsd)} a book` : "n/a"}
          sub={current != null || control ? shareSourceText(control, file) : "the bot reports it once it runs"}
          valueSub={paused ? "paused" : undefined}
          help={bot === "pumpfun" ? "The stake of each trade as a share of the wallet's SOL plus what is open." : "The share of the wallet's value the books may use."}
        />
        {p.rows}
      </div>
      {pausedLine && (
        <Notice tone="warning" className="mt-3" title={pausedLine.charAt(0).toUpperCase() + pausedLine.slice(1)}>
          {bot === "pumpfun" ? "No new buys; open positions are still sold by their exits." : "No book trades; your conversions still work."}
        </Notice>
      )}
      {requested != null && current != null && Math.abs(requested - current) > 1e-9 && <p className="mt-2 text-[13px] text-muted">You asked for {shareText(requested)}; {shareText(current)} is in force.</p>}
      {control?.note && <Notice tone="info" className="mt-3">{control.note}</Notice>}
      {control && !control.controlOk && <Notice tone="warning" className="mt-3">The control file could not be read; the last good values stay.</Notice>}
      {low && <Notice tone="warning" className="mt-3">{low}</Notice>}

      <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label="Share of the wallet">
        {SHARE_BUTTONS.map((x, i) =>
          shareButton({ kind: "share", share: x }, shareText(x), off || refusals[i] != null, current != null && Math.abs(current - x) < 1e-9 ? "primary" : "secondary"),
        )}
      </div>
      {hint && <p className="mt-2 text-[13px] text-muted">{hint}</p>}
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <Field label="Other share (%)" error={parsed.error ?? customRefusal ?? undefined} className="w-40">
          <input className={inputCls} inputMode="decimal" value={p.custom} placeholder="12.5" onChange={(e) => p.onCustom(e.target.value)} aria-label="Other share in percent" disabled={!can} />
        </Field>
        {shareButton({ kind: "share", share: parsed.share ?? 0 }, "Set", off || parsed.share == null || customRefusal != null, "secondary")}
        {hasOverride(control, file) && (
          <Button size="sm" variant="ghost" icon={RotateCcw} disabled={off} onClick={act({ kind: "reset" })}>
            Back to the confirmation file
          </Button>
        )}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {paused ? (
          <ConfirmAction icon={Play} danger={false} variant="primary" disabled={off} title={bot === "pumpfun" ? "Start the bot again?" : "Start the books again?"} confirmLabel="Start" question={confirmQuestion(start, bot)} onConfirm={act(start)}>
            Start
          </ConfirmAction>
        ) : (
          <Button icon={Pause} variant="secondary" disabled={off} onClick={act({ kind: "stop" })}>
            Stop
          </Button>
        )}
      </div>
      {!can && <p className="mt-3 text-sm text-muted">The master controls work through the connected backend on the server; the desktop app only shows them.</p>}
      {p.err && <Notice tone="danger" className="mt-3">{p.err}</Notice>}
      {p.msg && <p className="mt-3 text-sm text-muted">{p.msg}</p>}
    </Section>
  );
}

const DONE: Record<string, string> = {
  stop: "Stopped. The bot reads it within a few seconds.",
  start: "Started. The bot reads it within a few seconds.",
  reset: "Back to the confirmation file's share.",
};

/** The panel with its state: the custom field, the request on its way, the answer. */
export function MasterPanel({ api, onDone, ...props }: MasterProps & { api: (p: ControlPatch) => Promise<unknown>; onDone: () => void }) {
  const [custom, setCustom] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const send = async (patch: ControlPatch) => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      await api(patch);
      setMsg(patch.share != null ? `Share set to ${shareText(patch.share)}. The bot reads it within a few seconds.` : DONE[patch.resetShare ? "reset" : patch.paused ? "stop" : "start"]);
      if (patch.share != null) setCustom("");
      onDone();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return <MasterView {...props} custom={custom} onCustom={setCustom} busy={busy} msg={msg} err={err} send={(p) => void send(p)} />;
}

/** The pump.fun bot's panel, from its view. */
export function pumpfunMasterProps(v: PumpfunView): MasterProps {
  const s = v.status;
  const kind = limitsKind(s?.control?.limits, s?.limits?.kind, s?.ack?.limits);
  return {
    bot: "pumpfun",
    control: s?.control ?? null,
    file: v.control ?? null,
    kind,
    ackShare: s?.control?.ackShare ?? s?.ack?.stakeShare ?? null,
    low: s?.low ?? null,
    can: canControl(),
    rows: (
      <>
        <Row label="Stake per trade" value={sol(s?.stake?.sol ?? null, false, 3)} sub={s?.stake?.why ?? undefined} help="What the next buy stakes, as the live service works it out." />
        {kind === "wallet" && <Row label="Daily loss, total budget" value={WALLET_LIMIT} help="With limits=wallet there is no daily loss limit and no total budget: the wallet's SOL is what can be lost." />}
      </>
    ),
  };
}

export function PumpfunMaster({ v, onDone }: { v: PumpfunView; onDone: () => void }) {
  return <MasterPanel {...pumpfunMasterProps(v)} api={pumpfunControl} onDone={onDone} />;
}

/** The on-chain trader's panel, from its view. */
export function onchainMasterProps(v: OnchainView): MasterProps {
  const s = v.status;
  const lim = s?.limits;
  const kind = limitsKind(s?.control?.limits, lim?.kind, s?.ack?.limits);
  return {
    bot: "onchain",
    control: s?.control ?? null,
    file: v.control ?? null,
    kind,
    ackShare: null,
    low: s?.low ?? null,
    can: canControlOnchain(),
    rows: (
      <>
        {s?.control?.bookUsd != null && <Row label="Per book" value={usdText(s.control.bookUsd)} sub={s.control.ackBookUsd != null ? `file ${usdText(s.control.ackBookUsd)}` : undefined} help="The US dollars each book may use now." />}
        <Row label="Per swap, at most" value={usdText(lim?.maxTradeUsd)} help={kind === "wallet" ? "A quarter of the wallet's value." : "The confirmation file's cap."} />
        <Row label="In all, at most" value={usdText(lim?.maxTotalUsd)} help={kind === "wallet" ? "The wallet's value." : "The confirmation file's cap."} />
        <Row label="Daily loss limit" value={kind === "wallet" ? WALLET_LIMIT : usdText(lim?.maxDailyLossUsd)} />
      </>
    ),
  };
}

export function OnchainMaster({ v, onDone }: { v: OnchainView; onDone: () => void }) {
  return <MasterPanel {...onchainMasterProps(v)} api={onchainControl} onDone={onDone} />;
}
