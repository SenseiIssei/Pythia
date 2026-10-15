import { useCallback, useEffect, useMemo, useState } from "react";
import { Bitcoin, Pause, Pencil, Play, Plane, Plus, Square } from "lucide-react";
import {
  BigNumber,
  Button,
  Card,
  Change,
  Chip,
  ConfirmSheet,
  Empty,
  ListRow,
  MiniChart,
  Page,
  Segmented,
  Sheet,
  Skeleton,
  money,
  signedPct,
  type ChipTone,
} from "../design/flows";
import {
  CARE,
  amountProblem,
  cardModel,
  careOf,
  demoProblem,
  floorFor,
  parseAmount,
  startConfig,
  toneOf,
  totals,
  vsBtcText,
  type Care,
  type CardModel,
  type PracticeAccount,
} from "../flows/autopilotView";
import { LIVE_EDIT_PHRASE, editForm, forwardLine, isActive, planEdit, type EditForm } from "../autopilot";
import { practiceAutopilots } from "../practice";
import { useStore } from "../store";
import { useAdvanced } from "../uiMode";
import { autopilotVenue, exchangeName } from "../venueNames";
import { Autopilot as AutopilotDetails, useAutopilotApi, type AutopilotApi } from "./Autopilot";
import type { AutopilotStatus, Venue } from "../types";

const MODE_CHIP: Record<CardModel["mode"], { label: string; tone: ChipTone }> = {
  paper: { label: "Practice money", tone: "neutral" },
  demo: { label: "Demo account", tone: "neutral" },
  live: { label: "Real money", tone: "bad" },
};

const STATUS_TONE: Record<CardModel["status"]["tone"], ChipTone> = {
  good: "good",
  warn: "warn",
  neutral: "neutral",
  bad: "bad",
};

function useNow(every = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), every);
    return () => clearInterval(t);
  }, [every]);
  return now;
}

/**
 * The autopilots, one calm card each: what it is worth, plus or minus, how
 * that compares with holding Bitcoin, what it holds and which strategies run
 * it. Start, edit, pause and stop are sheets. The old Practice page lives
 * here now.
 */
export function Autopilots() {
  const api = useAutopilotApi();
  const { positions, strategies, limits } = useStore();
  const advanced = useAdvanced();
  const now = useNow();
  const [starting, setStarting] = useState(false);
  const [details, setDetails] = useState(false);

  const names = useMemo(() => Object.fromEntries(strategies.map((s) => [s.id, s.name])), [strategies]);
  const shown = practiceAutopilots(api.autopilots, now);
  const t = totals(api.autopilots);
  const btc = api.btc ? { times: api.btc.times, closes: api.btc.closes } : null;

  return (
    <Page
      title="Autopilot"
      subtitle="It trades an amount for you, on practice money, until you stop it."
      right={
        shown.length > 0 && (
          <Button onClick={() => setStarting(true)} icon={Plus}>
            New
          </Button>
        )
      }
    >
      {api.mocked && <Chip tone="warn">Sample data ({api.mocked})</Chip>}
      {limits.killSwitch && t.count > 0 && (
        <Card>
          <p className="fl-down text-[15px] font-semibold">Kill switch is on</p>
          <p className="fl-muted text-sm">Nothing new is bought until you switch it off. Selling still works.</p>
        </Card>
      )}

      {api.loading ? (
        <Card>
          <Skeleton className="h-4 w-24" />
          <Skeleton className="mt-3 h-9 w-48" />
          <Skeleton className="mt-3 h-14 w-full" />
        </Card>
      ) : shown.length === 0 ? (
        <Card>
          <Empty
            icon={Plane}
            title="No autopilot yet"
            action={
              <Button onClick={() => setStarting(true)} icon={Plus}>
                Start an autopilot
              </Button>
            }
          >
            Pick an amount and how careful it should be. It trades practice money, so nothing real can be lost.
          </Empty>
        </Card>
      ) : (
        <>
          {t.count > 1 && (
            <Card>
              <BigNumber label={`${t.count} autopilots together`} value={money(t.value)} />
              <div className="mt-1">
                <Change usd={t.pnl} pct={t.pnlPct} tone={toneOf(t.pnl)} />
              </div>
            </Card>
          )}
          {shown.map((s) => (
            <AutopilotCard key={s.config.id} s={s} model={cardModel(s, positions, now, btc, names)} api={api} />
          ))}
        </>
      )}

      {advanced && (
        <div className="pt-2">
          <Button variant="ghost" onClick={() => setDetails((d) => !d)}>
            {details ? "Hide full setup and analysis" : "Full setup and analysis"}
          </Button>
        </div>
      )}
      {advanced && details && (
        // The detailed page keeps real-money starts and the full analysis.
        <div className="rounded-2xl bg-cyber-bg p-3">
          <AutopilotDetails />
        </div>
      )}

      <StartSheet open={starting} onClose={() => setStarting(false)} onStart={api.start} />
    </Page>
  );
}

// ── one card ────────────────────────────────────────────────────────────────

function AutopilotCard({ s, model: m, api }: { s: AutopilotStatus; model: CardModel; api: AutopilotApi }) {
  const [editing, setEditing] = useState(false);
  const [asking, setAsking] = useState<"pause" | "stop" | null>(null);
  const [sell, setSell] = useState(s.config.flattenOnStop);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const mode = MODE_CHIP[m.mode];

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setErr("");
    try {
      await fn();
      setAsking(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  }

  const close = useCallback(() => {
    setAsking(null);
    setErr("");
  }, []);

  return (
    <Card as="article" label={m.name}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="min-w-0 truncate text-base font-semibold">{m.name}</h2>
        <div className="flex flex-wrap gap-1.5">
          <Chip tone={STATUS_TONE[m.status.tone]}>{m.status.label}</Chip>
          <Chip tone={mode.tone}>{mode.label}</Chip>
        </div>
      </div>

      <div className="mt-2">
        <BigNumber value={money(m.value)} />
        <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1">
          <Change usd={m.pnl} pct={m.pnlPct} tone={m.tone} />
          <span className="fl-muted text-sm">of {money(m.amount, 0)}</span>
        </div>
      </div>

      <div className="mt-3">
        <MiniChart data={m.chart} tone={m.tone} label={`Value of ${m.name} since it started`} />
      </div>

      <ul className="mt-2 divide-y divide-line border-t border-line">
        <li>
          <ListRow
            icon={Bitcoin}
            title={vsBtcText(m.vsBtcPts)}
            subtitle={m.btcPct != null ? `Bitcoin ${signedPct(m.btcPct, 1)} · this ${signedPct(m.pnlPct, 1)}` : "Needs a Bitcoin price from its start"}
          />
        </li>
      </ul>

      <h3 className="fl-muted mt-3 text-xs font-semibold uppercase tracking-wider">Holds</h3>
      {m.holdings.length === 0 ? (
        <p className="mt-1 text-sm">Cash</p>
      ) : (
        <ul className="mt-1 divide-y divide-line">
          {m.holdings.map((h) => (
            <li key={h.marketId} className="flex items-center justify-between gap-3 py-2">
              <span className="min-w-0 truncate text-[15px] font-semibold">{h.coin}</span>
              <span className="text-right">
                <span className="fl-num block text-[15px] font-semibold">{money(h.value)}</span>
                <Change pct={h.pnlPct} tone={toneOf(h.pnl)} size="sm" />
              </span>
            </li>
          ))}
        </ul>
      )}

      <h3 className="fl-muted mt-3 text-xs font-semibold uppercase tracking-wider">Strategies</h3>
      {m.strategies.length === 0 ? (
        <p className="mt-1 text-sm">Pythia picks them when it starts.</p>
      ) : (
        <ul className="mt-1 space-y-1.5">
          {m.strategies.map((st) => (
            <li key={st.id} className="text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="min-w-0 truncate">{st.name}</span>
                <span className="fl-num shrink-0 font-semibold">{st.pct}%</span>
              </div>
              <div className="fl-surface-2 mt-1 h-1.5 overflow-hidden rounded-full" aria-hidden>
                <div className="h-full rounded-full" style={{ width: `${st.pct}%`, background: "var(--color-text)" }} />
              </div>
            </li>
          ))}
        </ul>
      )}

      <p className="fl-muted mt-3 text-sm">{m.status.line}</p>
      {m.active && s.forward && <p className="fl-muted mt-1 text-sm">{forwardLine(s.forward)?.text}</p>}

      {m.active && (
        <div className="mt-4 grid grid-cols-3 gap-2">
          <Button variant="secondary" icon={Pencil} onClick={() => setEditing(true)}>
            Edit
          </Button>
          {s.state === "paused" ? (
            <Button variant="secondary" icon={Play} disabled={busy} onClick={() => void run(() => api.resume(m.id))}>
              Resume
            </Button>
          ) : (
            <Button variant="secondary" icon={Pause} onClick={() => setAsking("pause")}>
              Pause
            </Button>
          )}
          <Button variant="secondary" icon={Square} onClick={() => setAsking("stop")}>
            Stop
          </Button>
        </div>
      )}
      {err && !asking && (
        <p role="alert" className="fl-down mt-2 text-sm">
          {err}
        </p>
      )}

      <ConfirmSheet
        open={asking === "pause"}
        title="Pause this autopilot?"
        body="It buys nothing new while paused. What it holds stays, and its loss limits keep watching. You can resume any time."
        confirm="Pause"
        busy={busy}
        error={err}
        onClose={close}
        onConfirm={() => void run(() => api.pause(m.id))}
      />
      <ConfirmSheet
        open={asking === "stop"}
        title="Stop this autopilot?"
        body="It stops for good. You cannot restart it, only start a new one."
        confirm="Stop"
        danger
        busy={busy}
        error={err}
        onClose={close}
        onConfirm={() => void run(() => api.stop(m.id, sell))}
      >
        <label className="mt-4 flex items-center justify-between gap-3 text-[15px]">
          <span>
            Sell what it holds
            <span className="fl-muted block text-sm">{sell ? "Back to cash right away." : "Positions stay open."}</span>
          </span>
          <input type="checkbox" className="h-5 w-5 shrink-0" checked={sell} onChange={(e) => setSell(e.target.checked)} />
        </label>
      </ConfirmSheet>

      {editing && <EditSheet s={s} api={api} onClose={() => setEditing(false)} />}
    </Card>
  );
}

// ── the guided start ───────────────────────────────────────────────────────

const AMOUNT_CHIPS = [500, 1000, 5000];
const CARE_ORDER: Care[] = ["low", "medium", "high"];

function Choice({ on, title, detail, onClick, disabled }: { on: boolean; title: string; detail: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={on}
      disabled={disabled}
      onClick={onClick}
      className={`fl-focus w-full rounded-2xl border-2 p-4 text-left transition-colors disabled:opacity-40 ${on ? "" : "fl-line"}`}
      style={{ borderColor: on ? "var(--color-text)" : "var(--color-line)" }}
    >
      <span className="block text-[15px] font-semibold">{title}</span>
      <span className="fl-muted block text-sm">{detail}</span>
    </button>
  );
}

function StartSheet({ open, onClose, onStart }: { open: boolean; onClose: () => void; onStart: AutopilotApi["start"] }) {
  const { live, cryptoCostVenue } = useStore();
  const [step, setStep] = useState(1);
  const [amount, setAmount] = useState("1000");
  const [care, setCare] = useState<Care>("medium");
  const [account, setAccount] = useState<PracticeAccount>("paper");
  const [assetClass, setAssetClass] = useState<Venue>("crypto");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const amountErr = amountProblem(amount);
  const demoErr = demoProblem(live, assetClass);
  const n = parseAmount(amount);
  const floor = Number.isFinite(n) ? floorFor(n, care) : null;
  const venue = autopilotVenue(account, assetClass, live, cryptoCostVenue);

  const reset = useCallback(() => {
    setStep(1);
    setErr("");
    setBusy(false);
    onClose();
  }, [onClose]);

  async function start() {
    setBusy(true);
    setErr("");
    try {
      await onStart(startConfig({ amount, care, account, assetClass }, venue, Date.now()));
      reset();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  const canNext = step === 1 ? !amountErr : step === 2 ? true : !(account === "demo" && demoErr) && !busy;

  return (
    <Sheet
      open={open}
      onClose={reset}
      title="New autopilot"
      footer={
        <div className="grid grid-cols-2 gap-2">
          <Button variant="secondary" full onClick={() => (step === 1 ? reset() : setStep(step - 1))}>
            {step === 1 ? "Cancel" : "Back"}
          </Button>
          <Button full disabled={!canNext} onClick={() => (step < 3 ? setStep(step + 1) : void start())}>
            {step < 3 ? "Next" : busy ? "Starting" : "Start"}
          </Button>
        </div>
      }
    >
      <div className="mb-4 flex items-center gap-1.5" aria-label={`Step ${step} of 3`}>
        {[1, 2, 3].map((i) => (
          <span key={i} className="h-1 flex-1 rounded-full" style={{ background: i <= step ? "var(--color-text)" : "var(--color-line)" }} />
        ))}
      </div>

      {step === 1 && (
        <div>
          <h3 className="text-lg font-semibold">How much?</h3>
          <p className="fl-muted text-sm">Practice money. Nothing real moves.</p>
          <label className="mt-3 block">
            <span className="sr-only">Amount in US dollars</span>
            <div className="relative">
              <span className="fl-muted pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-2xl font-bold">$</span>
              <input
                inputMode="decimal"
                className="fl-input fl-num text-2xl font-bold"
                style={{ paddingLeft: 36 }}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                aria-invalid={!!amountErr}
              />
            </div>
          </label>
          <div className="mt-3 flex flex-wrap gap-2">
            {AMOUNT_CHIPS.map((a) => (
              <button key={a} type="button" onClick={() => setAmount(String(a))} className="fl-focus fl-surface-2 rounded-full px-3 py-1.5 text-sm font-semibold">
                {money(a, 0)}
              </button>
            ))}
          </div>
          {amountErr && amount.trim() !== "" && <p className="fl-down mt-2 text-sm">{amountErr}</p>}
        </div>
      )}

      {step === 2 && (
        <div>
          <h3 className="text-lg font-semibold">How careful?</h3>
          <p className="fl-muted text-sm">It stops itself when a limit is reached.</p>
          <div role="radiogroup" aria-label="How careful" className="mt-3 space-y-2">
            {CARE_ORDER.map((c) => (
              <Choice key={c} on={care === c} title={CARE[c].label} detail={CARE[c].detail} onClick={() => setCare(c)} />
            ))}
          </div>
          {floor != null && <p className="fl-muted mt-3 text-sm">Lowest it can go before it stops: {money(floor, 0)}.</p>}
        </div>
      )}

      {step === 3 && (
        <div>
          <h3 className="text-lg font-semibold">Practice account</h3>
          <p className="fl-muted text-sm">Where the practice trades happen.</p>
          <div className="mt-3">
            <Segmented
              label="Markets"
              value={assetClass}
              onChange={setAssetClass}
              options={[
                { id: "crypto", label: "Crypto" },
                { id: "alpaca", label: "US shares" },
              ]}
            />
          </div>
          <div role="radiogroup" aria-label="Practice account" className="mt-3 space-y-2">
            <Choice on={account === "paper"} title="Pythia practice" detail="Simulated trades on real prices." onClick={() => setAccount("paper")} />
            <Choice
              on={account === "demo"}
              title={`${exchangeName(venue) || "Exchange"} demo account`}
              detail={demoErr ?? "Real orders on the exchange's practice balance."}
              disabled={!!demoErr}
              onClick={() => setAccount("demo")}
            />
          </div>
          <div className="fl-surface-2 mt-4 rounded-2xl p-3 text-sm">
            <p>
              <b className="fl-num">{Number.isFinite(n) ? money(n, 0) : "n/a"}</b>, {CARE[care].label.toLowerCase()} care,{" "}
              {account === "paper" ? "Pythia practice" : "demo account"}.
            </p>
            <p className="fl-muted">Pythia picks the strategies and checks them again every day.</p>
          </div>
          {err && (
            <p role="alert" className="fl-down mt-3 text-sm">
              {err}
            </p>
          )}
        </div>
      )}
    </Sheet>
  );
}

// ── edit ────────────────────────────────────────────────────────────────────

function EditSheet({ s, api, onClose }: { s: AutopilotStatus; api: AutopilotApi; onClose: () => void }) {
  const [form, setForm] = useState<EditForm>(() => editForm(s.config));
  const [accept, setAccept] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const live = s.config.mode === "live";
  const plan = planEdit(s.config, form);
  const currentCare = careOf({
    onTakeProfit: "stop",
    maxLossPct: form.lossPct ? Number(form.lossPct) : null,
    maxLossUsd: form.lossUsd ? Number(form.lossUsd) : null,
    trailingPct: form.trailing ? Number(form.trailing) : null,
  });
  const careValue: Care | "custom" = currentCare ?? "custom";

  function setCareLevel(c: Care | "custom") {
    if (c === "custom") return;
    const st = CARE[c].stop;
    setForm((f) => ({ ...f, lossPct: st.maxLossPct ? String(st.maxLossPct) : "", lossUsd: "", trailing: st.trailingPct ? String(st.trailingPct) : "" }));
  }

  const needsPhrase = live && typed.trim().toUpperCase() !== LIVE_EDIT_PHRASE;
  const can = plan.changed && plan.problems.length === 0 && (!plan.looser || accept) && !needsPhrase && !busy;

  async function save() {
    setBusy(true);
    setErr("");
    try {
      await api.update(s.config.id, plan.update, live || plan.looser);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  const ids = Object.keys(form.weights);

  return (
    <Sheet
      open
      onClose={onClose}
      title="Edit autopilot"
      footer={
        <div className="grid grid-cols-2 gap-2">
          <Button variant="secondary" full onClick={onClose}>
            Cancel
          </Button>
          <Button full disabled={!can} onClick={() => void save()}>
            {busy ? "Saving" : "Save"}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <label className="block">
          <span className="text-sm font-semibold">Name</span>
          <input className="fl-input mt-1" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </label>
        <label className="block">
          <span className="text-sm font-semibold">Amount</span>
          <input inputMode="decimal" className="fl-input fl-num mt-1" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
        </label>

        <div>
          <span className="text-sm font-semibold">How careful</span>
          <div className="mt-1">
            <Segmented
              label="How careful"
              value={careValue}
              onChange={setCareLevel}
              options={[
                { id: "low", label: "Low" },
                { id: "medium", label: "Medium" },
                { id: "high", label: "High" },
                ...(careValue === "custom" ? [{ id: "custom" as const, label: "Custom" }] : []),
              ]}
            />
          </div>
          <p className="fl-muted mt-1 text-sm">
            {careValue === "custom"
              ? `Own limits: ${form.lossPct ? `${form.lossPct}% loss` : "no % limit"}${form.lossUsd ? `, $${form.lossUsd}` : ""}${form.trailing ? `, ${form.trailing}% from its best` : ""}.`
              : CARE[careValue].detail}
          </p>
        </div>

        <div>
          <span className="text-sm font-semibold">Strategies</span>
          <div className="mt-1">
            <Segmented
              label="Who picks the strategies"
              value={form.pick}
              onChange={(p) => setForm({ ...form, pick: p })}
              options={[
                { id: "auto", label: "Pythia picks" },
                { id: "manual", label: "Keep these" },
              ]}
            />
          </div>
          {form.pick === "manual" && (
            <ul className="mt-2 space-y-2">
              {ids.length === 0 && <li className="fl-muted text-sm">It has no fixed strategies yet. Pick them in the full setup.</li>}
              {ids.map((id) => (
                <li key={id} className="flex items-center justify-between gap-3">
                  <span className="min-w-0 truncate text-sm">{s.bySleeve.find((b) => b.strategyId === id)?.name ?? id}</span>
                  <input
                    aria-label={`Share for ${id}`}
                    inputMode="decimal"
                    className="fl-input fl-num w-24 text-right"
                    style={{ minHeight: 40 }}
                    value={form.weights[id]}
                    onChange={(e) => setForm({ ...form, weights: { ...form.weights, [id]: e.target.value } })}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>

        {plan.problems.length > 0 && (
          <ul className="fl-down space-y-0.5 text-sm">
            {plan.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
        {plan.looser && plan.problems.length === 0 && (
          <label className="flex items-start gap-3 text-sm">
            <input type="checkbox" className="mt-0.5 h-5 w-5 shrink-0" checked={accept} onChange={(e) => setAccept(e.target.checked)} />
            <span>This lets it lose more before it stops. I am fine with that.</span>
          </label>
        )}
        {live && (
          <label className="block text-sm">
            <span className="fl-down font-semibold">Real money. Type {LIVE_EDIT_PHRASE} to confirm.</span>
            <input className="fl-input mt-1" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
          </label>
        )}
        {!plan.changed && <p className="fl-muted text-sm">Nothing changed yet.</p>}
        {err && (
          <p role="alert" className="fl-down text-sm">
            {err}
          </p>
        )}
        {!isActive(s) && <p className="fl-muted text-sm">It has stopped and can no longer be changed.</p>}
      </div>
    </Sheet>
  );
}
