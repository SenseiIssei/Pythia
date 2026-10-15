import { useState } from "react";
import { CheckCircle2, Circle, Cpu, FlaskConical, Lock, Radio, RefreshCw, XCircle } from "lucide-react";
import { useStore } from "../store";
import { Badge, Button, Card, List, Notice, Page, Sheet, Sparkline, changeTone, inputCls, money, signedMoney } from "../design";
import { ConfirmAction, CostLines, KeyStats, More, Nothing, Row, Section, SwitchRow, Term, plural, share } from "../pagekit";
import { gateValue, stateInfo, strategyBlurb, strategySummary } from "../pagekit/picks";
import { researchAvailable, runValidation } from "../research";
import type { Gate, Passport, StrategyConfig } from "../types";
import { changeStrategyState } from "../strategyState";
import { cryptoDemoName, demoApiTestNote, demoIsApiTestOnly } from "../venueNames";

export function Strategies() {
  const { strategies, passports } = useStore();
  const list = strategies.filter((s) => s.id !== "manual");
  const sum = strategySummary(list);
  return (
    <Page title="Strategies" subtitle="Each one is a rule set that decides on its own when to buy or sell. Prove it with practice money, earn the passport, then switch to live on purpose.">
      {list.length > 0 && (
        <KeyStats
          items={[
            { label: "Result so far", value: signedMoney(sum.pnl), tone: changeTone(sum.pnl), sub: "All strategies together", help: "Profit or loss of every strategy on this page added up." },
            { label: "Running", value: `${sum.running} of ${sum.total}`, help: "Strategies that are switched on. Paused ones place no orders." },
            { label: "With real money", value: String(sum.live), tone: sum.live > 0 ? "warn" : "plain", help: "Strategies set to Live: they send real orders." },
          ]}
        />
      )}
      {list.length === 0 ? (
        <Card>
          <Nothing icon={Cpu} title="No strategies loaded yet">
            They arrive with the first update from the engine, usually within a second or two.
          </Nothing>
        </Card>
      ) : (
        <Section title="Your strategies" hint="Switch one off and it stops placing orders. Open its settings to tune it or run its checks." bare>
          <div className="space-y-4">
            {list.map((s) => (
              <StrategyCard key={s.id} s={s} passport={passports.get(s.id)} />
            ))}
          </div>
        </Section>
      )}
    </Page>
  );
}

function StrategyCard({ s, passport }: { s: StrategyConfig; passport?: Passport }) {
  const { setStrategyState, setStrategyParam, live: liveStatus } = useStore();
  const [confirm, setConfirm] = useState(false);
  const [typed, setTyped] = useState("");
  // Sliders edit a draft. The engine starts a strategy's record over on every
  // parameter change, so dragging through ten values must not reach it until
  // the person decides; "Apply" sends the draft once.
  const [draft, setDraft] = useState<Record<string, number>>({});
  const changed = s.params.filter((p) => draft[p.key] !== undefined && draft[p.key] !== p.value);
  function applyDraft() {
    for (const p of changed) setStrategyParam(s.id, p.key, draft[p.key]);
    setDraft({});
  }
  const [armErr, setArmErr] = useState("");

  const live = s.state === "live";
  const paused = s.state === "paused";
  const demo = s.state === "demo";
  const ready = passport?.liveReady ?? false;
  const info = stateInfo(s.state);
  const passed = passport ? passport.gates.filter((g) => g.status === "pass").length : 0;

  /** Every switch can be refused (demo keys missing, or an autopilot runs
   *  this strategy and sets its state itself); the refusal is shown, never dropped. */
  async function change(state: StrategyConfig["state"]) {
    setArmErr("");
    setArmErr(await changeStrategyState(setStrategyState, s.id, state));
  }

  async function armLive() {
    if (typed.trim() !== s.name) return;
    setArmErr("");
    try {
      await setStrategyState(s.id, "live");
      setConfirm(false);
      setTyped("");
    } catch (e) {
      // The engine is the authority: if it refuses, say why.
      setArmErr(String(e instanceof Error ? e.message : e));
    }
  }

  return (
    <Card as="article" label={s.name}>
      {/* Name, what it does, and its result. */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="break-words text-[17px] font-semibold tracking-tight text-ink">{s.name}</h3>
            <Badge tone={info.tone} title={info.means}>
              {info.label}
            </Badge>
          </div>
          <p className="mt-1 text-[13px] leading-snug text-muted">{strategyBlurb(s.kind)}</p>
        </div>
        <div className="shrink-0 text-right">
          <div className={`tabular text-[17px] font-semibold ${changeTone(s.pnl) === "up" ? "text-up" : changeTone(s.pnl) === "down" ? "text-down" : "text-ink"}`}>{signedMoney(s.pnl)}</div>
          <div className="tabular text-[13px] text-muted">{plural(s.trades, "trade")}</div>
          <div className="tabular flex items-center justify-end gap-1 text-[13px] text-muted">
            <Term k="Win Rate">{share(s.winRate)} won</Term>
          </div>
        </div>
      </div>

      {/* No chart until there is a record to draw: a flat line says nothing. */}
      {s.equityCurve.length > 1 && (
        <div className="mt-3">
          <Sparkline data={s.equityCurve} height={44} tone={s.pnl > 0 ? "up" : s.pnl < 0 ? "down" : "flat"} label={`${s.name} profit and loss over time`} fill />
        </div>
      )}

      {/* On or off. Off is "paused"; on again resumes with practice money. */}
      <div className="mt-2 border-t border-line">
        <SwitchRow
          label={paused ? "Switched off" : "Running"}
          hint={paused ? "Places no orders. Switching it on resumes with practice money." : info.means}
          on={!paused}
          onChange={(v) => void change(v ? "paper" : "paused")}
        />
      </div>

      {/* Where its orders go. */}
      {!paused && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <Button variant="secondary" size="sm" icon={FlaskConical} onClick={() => void change("paper")} disabled={s.state === "paper"}>
            Practice money
          </Button>
          {!live && s.venueClass !== "polymarket" && (
            <Button variant="secondary" size="sm" onClick={() => void change("demo")} disabled={demo}>
              Demo account
            </Button>
          )}
          {live ? (
            <Button variant="danger" size="sm" icon={Radio} onClick={() => void change("paper")}>
              Disarm live
            </Button>
          ) : (
            <Button variant="danger" size="sm" icon={ready ? Radio : Lock} onClick={() => setConfirm((c) => !c)} disabled={!ready}>
              Arm live
            </Button>
          )}
        </div>
      )}

      {!live && !ready && !paused && passport?.blockedReason && (
        <p className="mt-3 flex items-start gap-1.5 text-[13px] leading-snug text-muted">
          <Lock size={14} aria-hidden className="mt-0.5 shrink-0" />
          <span>Live is locked until its checks pass. The reason is under Settings, costs and checks.</span>
        </p>
      )}

      {armErr && !confirm && (
        <Notice tone="danger" className="mt-3">
          <span className="break-words">{armErr}</span>
        </Notice>
      )}
      {demo && (
        <p className="mt-3 text-[13px] leading-snug text-muted">
          Demo: orders go to {s.venueClass === "crypto" && cryptoDemoName(liveStatus) ? `${cryptoDemoName(liveStatus)}'s` : "the venue's"} demo account
          with its demo keys. Real API, virtual money, never in the tax record. Exits go back to the same demo account.
        </p>
      )}
      {demo && s.venueClass === "crypto" && demoIsApiTestOnly(liveStatus) && (
        <Notice tone="warning" className="mt-3">
          {demoApiTestNote(liveStatus)}
        </Notice>
      )}

      {changed.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-2xl bg-warn/10 px-4 py-3 text-[13px] text-ink">
          <span className="min-w-0 flex-1 basis-40">{changed.length === 1 ? "1 setting changed" : `${changed.length} settings changed`}, not applied yet.</span>
          {s.trades > 0 || live ? (
            <ConfirmAction
              title="Apply new settings?"
              danger={false}
              variant="secondary"
              size="sm"
              question={
                <>
                  New settings make it a different strategy, so its record of {s.trades} trades starts over
                  {live ? " and it goes back to practice money until its checks pass again" : ""}. Apply?
                </>
              }
              confirmLabel="Yes, apply"
              onConfirm={applyDraft}
            >
              Apply
            </ConfirmAction>
          ) : (
            <Button variant="secondary" size="sm" onClick={applyDraft}>
              Apply
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={() => setDraft({})}>
            Undo changes
          </Button>
        </div>
      )}

      <div className="mt-3 border-t border-line pt-1">
        <More title={`Settings, costs and checks${passport ? ` (${passed} of 8 passed)` : ""}`}>
          <div className="space-y-5">
            {!live && !ready && passport?.blockedReason && (
              <Notice tone="info" icon={Lock} title="Why live is locked">
                {passport.blockedReason} To check that keys and the broker work without a strategy, use the connection test
                on the Live page.
              </Notice>
            )}
            <List>
              <Row label="Markets" value={String(s.universe.length)} sub={<span className="break-all">{s.kind}</span>} help="How many markets it watches, and the kind of rule set it is." />
              <Row label="Budget" value={`${s.budgetPct}%`} />
              <Row label="Profit factor" value={s.profitFactor.toFixed(2)} />
              <Row label="Max Drawdown" value={money(s.maxDrawdown)} />
            </List>

            {s.ledger && s.trades > 0 && (
              <div>
                <h4 className="text-[15px] font-semibold text-ink">What it made and what it cost</h4>
                <CostLines pnl={s.ledger.pnl} />
              </div>
            )}

            {s.params.length > 0 && (
              <div>
                <h4 className="text-[15px] font-semibold text-ink">Settings</h4>
                <p className="text-[13px] text-muted">Changes wait until you press Apply.</p>
                <div className="mt-2 space-y-3">
                  {s.params.map((p) => {
                    const v = draft[p.key] ?? p.value;
                    return (
                      <label key={p.key} className="block">
                        <span className="flex items-center justify-between gap-3 text-[13px]">
                          <span className="min-w-0 text-muted">{p.label}</span>
                          <span className={`tabular shrink-0 font-semibold ${v !== p.value ? "text-warn" : "text-ink"}`}>
                            {v}
                            {v !== p.value && <span className="font-normal text-muted"> (was {p.value})</span>}
                          </span>
                        </span>
                        <input
                          type="range"
                          min={p.min}
                          max={p.max}
                          step={p.step}
                          value={v}
                          onChange={(e) => setDraft((d) => ({ ...d, [p.key]: Number(e.target.value) }))}
                          className="mt-1 w-full min-w-0 accent-accent"
                        />
                      </label>
                    );
                  })}
                </div>
              </div>
            )}

            {passport && <PassportView s={s} passport={passport} />}
          </div>
        </More>
      </div>

      {/* Arming live: type the name to confirm. */}
      <Sheet
        open={confirm && !live && ready}
        onClose={() => setConfirm(false)}
        title="Trade with real money?"
        footer={
          <div className="grid grid-cols-2 gap-2">
            <Button variant="secondary" full onClick={() => setConfirm(false)}>
              Cancel
            </Button>
            <Button variant="danger" full onClick={() => void armLive()} disabled={typed.trim() !== s.name}>
              Confirm live
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-[15px] text-muted">
          <p>
            Arming live routes <b className="text-ink">real orders</b> using this venue's API keys. Type the strategy name to
            confirm.
          </p>
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={s.name}
            aria-label={`Type ${s.name} to confirm`}
            className={`${inputCls} focus:border-down`}
          />
          {armErr && (
            <p role="alert" className="break-words text-sm text-down">
              {armErr}
            </p>
          )}
          <p className="text-[13px] leading-snug">
            Live sends orders only once execution is armed on the Live page, and starts at the venue's smallest size until
            gate 8 is earned. See SAFETY.md.
          </p>
        </div>
      </Sheet>
    </Card>
  );
}

/** The eight validation gates as a checklist: a tick for pass, a cross for fail, an empty circle for pending. */
function PassportView({ s, passport }: { s: StrategyConfig; passport: Passport }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const canRun = researchAvailable();
  const passed = passport.gates.filter((g) => g.status === "pass").length;

  async function check() {
    setBusy(true);
    setErr("");
    try {
      await runValidation(s.id);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    }
    setBusy(false);
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-[15px] font-semibold text-ink">
          <Term k="Strategy Passport">Strategy Passport</Term>
        </h4>
        <Badge tone={passport.liveReady ? "good" : "neutral"}>{passed} / 8 passed</Badge>
        {passport.stale && <Badge tone="warn">Settings changed since</Badge>}
        <span className="flex-1" />
        {canRun && (
          <Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => void check()} disabled={busy}>
            {busy ? "Checking" : passport.checkedAt ? "Re-run checks" : "Run checks"}
          </Button>
        )}
      </div>
      <List className="mt-1">
        {passport.gates.map((g) => (
          <GateRow key={g.id} gate={g} open={open === g.id} onToggle={() => setOpen(open === g.id ? null : g.id)} />
        ))}
      </List>
      <p className="mt-2 text-[13px] leading-snug text-muted">
        {passport.checkedAt ? `Gates 1 to 6 checked ${new Date(passport.checkedAt).toLocaleString()} on daily candles.` : "Gates 1 to 6 have not been checked yet."} Live
        needs gates 1 to 7 green; gate 8 is earned at minimum size after arming.
        {!canRun && " Checks need the desktop app or a connected backend."}
      </p>
      {err && (
        <Notice tone="danger" className="mt-2">
          <span className="break-words">{err}</span>
        </Notice>
      )}
    </div>
  );
}

function GateRow({ gate, open, onToggle }: { gate: Gate; open: boolean; onToggle: () => void }) {
  const Icon = gate.status === "pass" ? CheckCircle2 : gate.status === "fail" ? XCircle : Circle;
  const tone = gate.status === "pass" ? "text-up" : gate.status === "fail" ? "text-down" : "text-faint";
  const word = gate.status === "pass" ? "passed" : gate.status === "fail" ? "failed" : "not checked yet";
  return (
    <div>
      <button type="button" className="flex w-full items-center gap-2.5 py-2.5 text-left" onClick={onToggle} aria-expanded={open} title={gate.reason}>
        <Icon size={16} aria-hidden className={`shrink-0 ${tone}`} />
        <span className="sr-only">{word}:</span>
        <span className="tabular w-4 shrink-0 text-[13px] text-muted">{gate.id}</span>
        <span className="min-w-0 flex-1 text-[15px] text-ink">{gate.name}</span>
        <span className={`tabular shrink-0 text-[15px] font-semibold ${gate.status === "pending" ? "text-muted" : tone}`}>{gate.value === undefined ? "-" : gateValue(gate.value, gate.unit)}</span>
      </button>
      {open && (
        <div className="pb-2.5 pl-[3.25rem] text-[13px] leading-snug text-muted">
          <p>
            <span className="text-ink">{gate.measure}:</span> {gate.reason}
          </p>
          {gate.figures && gate.figures.length > 0 && (
            <p className="mt-1 flex flex-wrap gap-x-3">
              {gate.figures.map((f) => (
                <span key={f.label}>
                  {f.label} <span className="tabular text-ink">{gateValue(f.value, f.unit)}</span>
                </span>
              ))}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
