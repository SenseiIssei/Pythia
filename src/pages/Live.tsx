import { useEffect, useState } from "react";
import {
  Radio,
  ShieldAlert,
  Power,
  PlugZap,
  TriangleAlert,
  CheckCircle2,
  Circle,
  DollarSign,
  Timer,
  Gauge,
} from "lucide-react";
import { Card, PageHeader, Badge, Button, EmptyState, Toggle, inputCls } from "../components/ui";
import { useStore } from "../store";
import { DataHealthCard } from "../components/DataHealth";
import {
  liveMode,
  alpacaAccount,
  setLiveConfig,
  verifyVenue,
  liveDiagnostics,
  sendTestOrder,
  type AlpacaAccount,
  type MarketDiag,
} from "../live";
import type { Venue } from "../types";
import { cryptoDemoName, demoApiTestNote, demoIsApiTestOnly } from "../venueNames";

const ARM_PHRASE = "ARM LIVE";

/** Venues that have an implemented order path. Polymarket is read-only. */
const ROUTABLE: { venue: Venue; label: string; note: string }[] = [
  { venue: "alpaca", label: "Alpaca · equities", note: "US market hours" },
  { venue: "crypto", label: "Crypto exchange", note: "24/7 spot, long only" },
];

export function Live() {
  const { live } = useStore();
  const mode = liveMode();
  const [paper, setPaper] = useState(true);
  const [dryRun, setDryRun] = useState(false);
  const [venues, setVenues] = useState<Venue[]>(["alpaca"]);
  const [timeoutSec, setTimeoutSec] = useState(120);
  const [extendedHours, setExtendedHours] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [acct, setAcct] = useState<AlpacaAccount | null>(null);
  const [checks, setChecks] = useState<Record<string, { ok: boolean; text: string }>>({});

  // Reflect the engine's actual arm config once it reports back.
  useEffect(() => {
    if (live.armed) {
      setPaper(live.paper);
      setDryRun(live.dryRun);
      setVenues(live.venues);
      setTimeoutSec(live.timeoutSec);
      setExtendedHours(live.extendedHours);
    }
  }, [live.armed, live.paper, live.dryRun, live.venues, live.timeoutSec, live.extendedHours]);

  function toggleVenue(v: Venue, on: boolean) {
    setVenues((prev) => (on ? [...new Set([...prev, v])] : prev.filter((x) => x !== v)));
  }

  async function testConn() {
    setBusy(true);
    setAcct(null);
    setErr("");
    const next: Record<string, { ok: boolean; text: string }> = {};
    for (const v of venues) {
      try {
        next[v] = { ok: true, text: await verifyVenue(v, paper) };
      } catch (e) {
        next[v] = { ok: false, text: e instanceof Error ? e.message : String(e) };
      }
    }
    setChecks(next);
    if (venues.includes("alpaca")) {
      try {
        setAcct(await alpacaAccount(paper));
      } catch {
        // verifyVenue already reported the reason; no need to say it twice.
      }
    }
    setBusy(false);
  }

  async function arm() {
    setBusy(true);
    setMsg("");
    setErr("");
    try {
      await setLiveConfig({ armed: true, paper, dryRun, venues, timeoutSec, extendedHours });
      setConfirm("");
      setMsg("armed");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  }

  async function disarm() {
    setBusy(true);
    setMsg("");
    setErr("");
    try {
      await setLiveConfig({ armed: false, paper, dryRun, venues, timeoutSec, extendedHours });
      setMsg("disarmed");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  }

  if (mode === "none") {
    return (
      <div className="animate-fade-in mx-auto max-w-3xl">
        <PageHeader title="Live Execution" subtitle="Send real orders to a broker: gated, and paper first." />
        <Card>
          <EmptyState icon={Radio} title="Live execution needs the desktop app or a connected server">
            Real orders need a connection to a broker. Use the desktop app (keys in the OS keychain) or a backend server
            (keys in its environment). This browser version can only practise.
          </EmptyState>
        </Card>
      </div>
    );
  }

  const canArm = confirm.trim().toUpperCase() === ARM_PHRASE && !live.armed && venues.length > 0;
  const realMoney = live.armed && !live.paper && !live.dryRun;

  return (
    <div className="animate-fade-in mx-auto max-w-3xl">
      <PageHeader
        title="Live Execution"
        subtitle="Send real orders to a broker. Each venue is armed separately, paper endpoint first, and every order still passes the risk limits."
      />

      {/* status banner */}
      {live.armed ? (
        <div
          role="status"
          className={`mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border px-4 py-2.5 text-sm font-bold ${
            realMoney
              ? "border-danger/50 bg-danger/15 text-danger text-glow-red animate-pulse-red"
              : "border-warning/40 bg-warning/10 text-warning"
          }`}
        >
          <span className="flex flex-wrap items-center gap-x-2">
            <Radio size={15} aria-hidden /> Armed:{" "}
            {live.dryRun ? "dry-run, nothing is sent" : live.paper ? "paper endpoint, no real money" : "REAL MONEY"}
            {live.venues.length > 0 && <span className="font-normal opacity-80">· {live.venues.join(", ")}</span>}
          </span>
          <span className="font-mono text-xs">{live.pending} pending</span>
        </div>
      ) : (
        <div
          role="status"
          className="mb-4 flex items-center gap-2 rounded-xl border border-success/30 bg-success/[0.06] px-4 py-2.5 text-sm text-success"
        >
          <Power size={14} aria-hidden className="shrink-0" /> Disarmed: everything is simulated. No order leaves this
          machine.
        </div>
      )}

      <DemoCard />

      {/* Real positions cannot be closed by the simulator, so this is not a detail. */}
      {live.livePositions > 0 && !live.armed && (
        <div className="mb-4 flex items-start gap-3 rounded-lg border border-danger/50 bg-danger/10 px-4 py-3 text-sm">
          <TriangleAlert size={18} className="mt-0.5 shrink-0 text-danger" />
          <div className="text-cyber-text-dim">
            <div className="font-bold text-danger">
              {live.livePositions} real position{live.livePositions > 1 ? "s" : ""} still open at the venue
            </div>
            Disarming does not close them, and stop-losses cannot fire while disarmed. Re-arm to manage them from
            here, or flatten them in the venue's own dashboard.
          </div>
        </div>
      )}

      {/*
        The most confusing state to be in is "armed, and nothing is happening".
        Almost always it is one of: the market is closed, the account is
        restricted, the day-trade ceiling is reached, or the broker check has
        not landed yet. The engine already knows which — so say it plainly here
        rather than leaving the user to guess from an empty order book.
      */}
      {live.armed && live.blockedReason && (
        <div className="mb-4 flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 px-4 py-2 text-sm text-warning">
          <TriangleAlert size={15} className="mt-0.5 shrink-0" />
          <div>
            <div className="font-bold">New entries are on hold</div>
            <div className="text-cyber-text-dim">{live.blockedReason}</div>
            <div className="mt-1 text-[11px] text-cyber-text-faint">
              Exits are never blocked: an open position can always be closed.
            </div>
          </div>
        </div>
      )}

      <DataHealthCard />
      <ReadinessCard />
      <DiagnosticsCard />

      {live.broker && (
        <Card title="Broker session" className="mb-4">
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <Field
              label="US market"
              value={live.broker.marketOpen ? "open" : "closed"}
              good={live.broker.marketOpen}
            />
            <Field label="Equity" value={`$${live.broker.equity.toLocaleString(undefined, { maximumFractionDigits: 2 })}`} />
            <Field
              label="Buying power"
              value={`$${live.broker.buyingPower.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
            />
            <Field
              label="Day-trade cap"
              value={live.broker.dayTradeLimitReached ? "reached" : "clear"}
              good={!live.broker.dayTradeLimitReached}
            />
          </div>
          {!live.broker.marketOpen && live.broker.nextOpen && (
            <div className="mt-2 text-xs text-cyber-text-faint">Next open: {live.broker.nextOpen}</div>
          )}
          {live.broker.restricted && (
            <div className="mt-2 text-xs text-danger">Account restricted: {live.broker.restricted}</div>
          )}
          <div className="mt-2 text-[11px] text-cyber-text-faint">
            Checked {Math.max(0, Math.round((Date.now() - live.broker.checkedAt) / 1000))}s ago · live entries block
            once this is over 5 minutes old.
          </div>
        </Card>
      )}

      <Card className="mb-4 border-danger/30 bg-danger/5">
        <div className="flex items-start gap-3">
          <ShieldAlert size={18} className="mt-0.5 shrink-0 text-danger" />
          <div className="text-sm text-cyber-text-dim">
            <div className="font-bold text-danger text-glow-red">Real orders, real risk</div>
            When armed, orders from a <span className="text-accent">Live</span>-state strategy on an{" "}
            <span className="text-accent">enabled venue</span> are sent for real. Everything else stays paper. The
            global kill switch and every risk limit still gate each order. Start on the{" "}
            <span className="text-accent">paper endpoint</span> (real API, fake money); flip to real money only once
            you trust it. Not financial advice: read SAFETY.md.
          </div>
        </div>
      </Card>

      {/* venues */}
      <Card title="1 · Venues" className="mb-4">
        <div className="mb-3 text-sm text-cyber-text-dim">
          Each venue is armed separately. A venue you leave off keeps simulating even while the rest are live.
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {ROUTABLE.map(({ venue, label, note }) => {
            const connected = live.connected.includes(venue);
            return (
              <div
                key={venue}
                className="flex items-center justify-between rounded-lg border border-cyber-border bg-cyber-surface/40 px-3 py-2"
              >
                <div>
                  <div className="text-sm font-medium">{label}</div>
                  <div className="text-[11px] text-cyber-text-faint">
                    {connected ? note : "No keys yet: add them in Settings"}
                  </div>
                </div>
                <Toggle
                  label={`Arm ${label}`}
                  on={venues.includes(venue)}
                  onChange={(v) => toggleVenue(venue, v)}
                />
              </div>
            );
          })}
        </div>
        <div className="mt-2 text-[11px] text-cyber-text-faint">
          Polymarket is not listed: its odds are read-only and it never routes an order.
        </div>
      </Card>

      {/* connection test */}
      <Card
        title="2 · Connection"
        className="mb-4"
        right={
          <Badge tone={live.connected.length > 0 ? "green" : "neutral"}>
            {live.connected.length > 0 ? `${live.connected.length} connected` : "check keys"}
          </Badge>
        }
      >
        <div className="mb-3 text-sm text-cyber-text-dim">
          Check that your keys reach the {paper ? "paper" : "live"} endpoint before arming. Read-only: it places no
          order.{" "}
          {mode === "native"
            ? `Keys come from the OS keychain (Settings). Alpaca uses the ${paper ? "Alpaca paper account" : "Alpaca live account"} keys; the two accounts have separate key pairs.`
            : "Keys come from the server environment (Alpaca: APCA_API_KEY_ID / APCA_API_SECRET_KEY, or APCA_LIVE_* for the live endpoint)."}
        </div>
        <Button tone="cyan" icon={PlugZap} disabled={busy || venues.length === 0} onClick={testConn}>
          Test {paper ? "paper" : "live"} connection
        </Button>
        {Object.entries(checks).length > 0 && (
          <div className="mt-3 space-y-1 rounded-lg border border-cyber-border bg-cyber-surface/50 p-3 text-xs">
            {Object.entries(checks).map(([v, r]) => (
              <div key={v} className={`flex items-start gap-1.5 ${r.ok ? "text-success" : "text-danger"}`}>
                {r.ok ? (
                  <CheckCircle2 size={13} aria-label="works" className="mt-0.5 shrink-0" />
                ) : (
                  <TriangleAlert size={13} aria-label="failed" className="mt-0.5 shrink-0" />
                )}
                <span>
                  <span className="font-mono uppercase tracking-widest text-cyber-text-faint">{v}</span>: {r.text}
                </span>
              </div>
            ))}
          </div>
        )}
        {acct && (
          <div className="mt-3 grid grid-cols-2 gap-3 rounded-lg border border-cyber-border bg-cyber-surface/50 p-3 text-sm sm:grid-cols-4">
            <Field label="Status" value={acct.status} good={acct.status === "ACTIVE"} />
            <Field label="Endpoint" value={acct.paper ? "paper" : "live"} good={acct.paper} />
            <Field label="Buying power" value={`$${fmt(acct.buyingPower)}`} />
            <Field label="Day trades" value={String(acct.daytradeCount ?? 0)} />
          </div>
        )}
      </Card>

      {/* arm */}
      <Card title="3 · Arm" right={<DollarSign size={14} className="text-danger" />}>
        <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {/*
            Both toggles are inert while armed, and are shown that way.
            `setLiveConfig` is only sent by arm(), so flipping these mid-flight
            changed a local value and nothing else — the switch moved, the label
            said "Paper", and orders kept going to the live endpoint. Requiring a
            disarm to change endpoint is also the right safety behaviour: moving
            between fake and real money should be a deliberate re-arm, not a tap.
          */}
          <div
            className={`flex items-center justify-between rounded-lg border px-3 py-2 ${
              live.armed ? "border-cyber-border/50 bg-cyber-surface/20 opacity-60" : "border-cyber-border bg-cyber-surface/40"
            }`}
          >
            <div>
              <div className="text-sm font-medium">Endpoint</div>
              <div className="text-[11px] text-cyber-text-faint">
                {live.armed
                  ? "Locked while armed: disarm to change"
                  : paper
                    ? "Paper: no real money"
                    : "LIVE: real money"}
              </div>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className={paper ? "text-accent" : "text-danger"}>{paper ? "Paper" : "Live"}</span>
              <Toggle
                label="Use the live (real money) endpoint"
                on={!paper}
                disabled={live.armed}
                onChange={(v) => !live.armed && setPaper(!v)}
              />
            </div>
          </div>
          <div
            className={`flex items-center justify-between rounded-lg border px-3 py-2 ${
              live.armed ? "border-cyber-border/50 bg-cyber-surface/20 opacity-60" : "border-cyber-border bg-cyber-surface/40"
            }`}
          >
            <div>
              <div className="text-sm font-medium">Dry-run</div>
              <div className="text-[11px] text-cyber-text-faint">
                {live.armed ? "Locked while armed: disarm to change" : "Write down the orders it would send, send nothing"}
              </div>
            </div>
            <Toggle label="Dry-run" on={dryRun} disabled={live.armed} onChange={(v) => !live.armed && setDryRun(v)} />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-cyber-border bg-cyber-surface/40 px-3 py-2 sm:col-span-2">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-sm font-medium">
                <Timer size={13} aria-hidden /> Order timeout
              </div>
              <div className="text-[11px] text-cyber-text-faint">
                After this long, an unfilled order is <b>cancelled at the venue</b> and whatever filled is booked.
              </div>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <input
                type="range"
                min={15}
                max={900}
                step={15}
                value={timeoutSec}
                aria-label="Order timeout in seconds"
                onChange={(e) => setTimeoutSec(Number(e.target.value))}
                className="w-32"
              />
              <span className="w-12 text-right font-mono">{timeoutSec}s</span>
            </div>
          </div>
        </div>

        {/*
          Extended hours is the difference between "it trades" and "it trades
          only between 15:30 and 22:00 CEST". Off by default: the session is
          thin, spreads are wide, and no strategy here was validated on it.
        */}
        <div
          className={`mb-3 flex items-center justify-between rounded-lg border px-3 py-2 ${
            live.armed ? "border-cyber-border/50 bg-cyber-surface/20 opacity-60" : "border-cyber-border bg-cyber-surface/40"
          }`}
        >
          <div>
            <div className="text-sm font-medium">Extended hours</div>
            <div className="text-[11px] text-cyber-text-faint">
              {live.armed
                ? "Locked while armed: disarm to change"
                : live.broker?.extendedOpen && !live.broker?.marketOpen
                  ? `Pre/after-market is open right now${live.broker.sessionEnd ? ` until ${live.broker.sessionEnd} ET` : ""}: few buyers and sellers, wide spreads`
                  : "Trade 04:00–20:00 ET instead of 09:30–16:00 · whole-share limit orders only"}
            </div>
          </div>
          <Toggle
            label="Extended hours"
            on={extendedHours}
            disabled={live.armed}
            onChange={(v) => !live.armed && setExtendedHours(v)}
          />
        </div>

        {/* Switching to real money is a different decision from arming at all. */}
        {!live.armed && !paper && !dryRun && (
          <div className="mb-3 flex items-start gap-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm">
            <TriangleAlert size={15} className="mt-0.5 shrink-0 text-danger" />
            <div className="text-cyber-text-dim">
              <span className="font-bold text-danger">Real money.</span> Arming now routes orders to your live
              Alpaca account. This uses the <span className="text-accent">Alpaca live account</span> keys from Settings,
              not the paper ones. Test them there first if you have not.
            </div>
          </div>
        )}

        {!live.armed ? (
          <>
            <div className="mb-2 text-sm text-cyber-text-dim">
              Type <span className="font-bold text-danger">{ARM_PHRASE}</span> to enable order routing
              {!paper && !dryRun ? " with REAL MONEY" : ""}.
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder={ARM_PHRASE}
                aria-label={`Type ${ARM_PHRASE} to confirm`}
                spellCheck={false}
                className={`${inputCls} w-40 font-mono focus:border-danger`}
              />
              <Button tone="red" icon={Radio} disabled={!canArm || busy} onClick={arm}>
                Arm live
              </Button>
              {msg && <span className="text-xs text-cyber-text-dim">{msg}</span>}
            </div>
            {venues.length === 0 && (
              <div className="mt-2 text-xs text-warning">Enable at least one venue above.</div>
            )}
          </>
        ) : (
          <div className="flex items-center gap-2">
            <Button tone="cyan" icon={Power} disabled={busy} onClick={disarm}>
              Disarm: back to paper
            </Button>
            {msg && <span className="text-xs text-cyber-text-dim">{msg}</span>}
          </div>
        )}
        {err && <div className="mt-2 text-xs text-danger">{err}</div>}

        <ExecutionPolicyCard />

        <div className="mt-4 space-y-1 text-[11px] leading-snug text-cyber-text-faint">
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> Arming runs a read-only key check first and refuses if a venue does not answer.</div>
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> Only strategies set to <b>Live</b> (Strategies page) send entries; a position opened live also exits live.</div>
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> The kill switch, daily-loss, drawdown &amp; position caps gate every order first.</div>
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> Orders that cannot fill (market closed, no buying power) are refused before submission, not left hanging.</div>
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> Alpaca entries are refused while the market is closed, the account is restricted, or the broker check is stale. Exits never are.</div>
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> Whole-share Alpaca orders go out as marketable limits, so a thin or gapped book can't fill them at any price.</div>
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> An order that doesn't fill is cancelled at the venue, then re-read, so nothing is ever left working after Pythia gives up on it.</div>
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> Positions are reconciled against the broker every couple of minutes while armed; the broker is always treated as the source of truth.</div>
        </div>
      </Card>
    </div>
  );
}

/**
 * Adaptive execution — the learned table, and the switch.
 *
 * Execution is the only alpha here that does not require being right about the
 * market, so this shows the one number that matters: what each style actually
 * cost, measured against the price at the moment the decision was made.
 */
/** Where each venue's demo connection test buys its minimum size. */
const DEMO_TEST_MARKET: Record<string, string> = {
  crypto: "crypto:BTC/USD",
  // Alpaca's crypto book trades around the clock, so the test works on a weekend.
  alpaca: "alpaca:BTC/USD",
};

/**
 * The demo route: real API round trips against a venue's demo account, with
 * virtual money. Separate from arming: it needs demo keys (Settings), never the
 * ARM LIVE phrase, and never touches the live keys.
 */
function DemoCard() {
  const { live } = useStore();
  const ready = live.demoVenues ?? [];
  const [busy, setBusy] = useState("");
  const [out, setOut] = useState<Record<string, { ok: boolean; text: string }>>({});

  async function run(key: string, action: () => Promise<string>) {
    setBusy(key);
    try {
      const text = await action();
      setOut((o) => ({ ...o, [key]: { ok: true, text } }));
    } catch (e) {
      setOut((o) => ({ ...o, [key]: { ok: false, text: e instanceof Error ? e.message : String(e) } }));
    }
    setBusy("");
  }

  return (
    <Card className="mb-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Badge tone="purple">DEMO</Badge> Demo trading: real venue API, virtual money
        </div>
        <span className="font-mono text-xs text-cyber-text-faint">
          {live.demoPositions ?? 0} demo position{(live.demoPositions ?? 0) === 1 ? "" : "s"}
        </span>
      </div>
      <div className="mb-3 text-xs leading-snug text-cyber-text-dim">
        A strategy set to Demo sends its orders to the venue's demo account with the demo keys from Settings: signing,
        size rules, rejects, latency and partial fills are all real, the money is not. No arming needed, the risk
        limits still apply, and demo fills never reach the tax record. See docs/DEMO.md for which venues trade on real
        prices.
      </div>
      <div className="space-y-2">
        {ROUTABLE.map(({ venue, label }) => {
          const on = ready.includes(venue);
          const demoName = cryptoDemoName(live);
          const where = venue === "crypto" ? (demoName ? `${demoName} demo` : "no demo exchange") : "Alpaca paper account";
          const apiOnly = venue === "crypto" && demoIsApiTestOnly(live);
          return (
            <div key={venue} className="rounded-lg border border-cyber-border bg-cyber-bg/40 p-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm">
                  {label} <span className="text-xs text-cyber-text-faint">· {where}</span>
                </span>
                <Badge tone={on ? "purple" : "neutral"}>{on ? (apiOnly ? "API test only" : "demo ready") : "no demo keys"}</Badge>
              </div>
              {apiOnly && <div className="mt-1.5 text-xs text-warning">{demoApiTestNote(live)}</div>}
              {on && (
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button
                    tone="neutral"
                    icon={PlugZap}
                    disabled={busy !== ""}
                    onClick={() => void run(`${venue}:check`, () => verifyVenue(venue, true, true))}
                  >
                    Check demo account
                  </Button>
                  <Button
                    tone="purple"
                    disabled={busy !== ""}
                    onClick={() => void run(`${venue}:test`, () => sendTestOrder(DEMO_TEST_MARKET[venue], 0, true))}
                  >
                    Demo connection test
                  </Button>
                </div>
              )}
              {[`${venue}:check`, `${venue}:test`].map((k) =>
                out[k] ? (
                  <div key={k} className={`mt-1.5 text-xs ${out[k].ok ? "text-success" : "text-danger"}`}>
                    {out[k].text}
                  </div>
                ) : null
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function ExecutionPolicyCard() {
  const { execution, adaptiveExecution, setAdaptiveExecution } = useStore();

  const STYLE_LABEL: Record<string, string> = {
    passive: "Rest inside the spread",
    join: "Sit at the touch",
    cross: "Take the offer",
  };

  return (
    <div className="mt-4 rounded-lg border border-cyber-border bg-cyber-surface/40 p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-1.5 text-sm font-medium">
          <Gauge size={14} className="text-purple-neon" /> Adaptive execution
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className={adaptiveExecution ? "text-purple-neon" : "text-cyber-text-faint"}>
            {adaptiveExecution ? "learning" : "always cross"}
          </span>
          <Toggle label="Adaptive execution" on={adaptiveExecution} onChange={setAdaptiveExecution} />
        </div>
      </div>

      <div className="mb-3 text-[11px] leading-snug text-cyber-text-faint">
        Crossing the spread on a signal that stays valid for hours is pure waste. With this on,
        orders may rest inside the spread instead, and the policy learns from what each choice
        actually cost, measured against the price at decision time, not the fill. An order that never fills
        is charged a penalty, because the signal was acted on late or not at all.
        {!adaptiveExecution && " While off, every order crosses, but costs are still recorded, so turning it on starts with real data."}
      </div>

      {execution.length === 0 ? (
        <div className="text-xs text-cyber-text-faint">
          Nothing measured yet. Rows appear once live orders have completed.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] uppercase tracking-widest text-cyber-text-faint">
                <th className="py-1 text-left font-normal">Situation</th>
                <th className="py-1 text-left font-normal">Style</th>
                <th className="py-1 text-right font-normal">Cost</th>
                <th className="py-1 text-right font-normal">Filled</th>
                <th className="py-1 text-right font-normal">Missed</th>
              </tr>
            </thead>
            <tbody>
              {execution.map((r) => (
                <tr key={`${r.context}-${r.style}`} className="border-t border-cyber-border/50">
                  <td className="py-1 font-mono text-cyber-text-dim">{r.context}</td>
                  <td className="py-1">{STYLE_LABEL[r.style] ?? r.style}</td>
                  <td
                    className={`py-1 text-right font-mono ${
                      r.meanCostBps <= 0 ? "text-success" : "text-cyber-text"
                    }`}
                  >
                    {r.meanCostBps > 0 ? "+" : ""}
                    {r.meanCostBps.toFixed(1)}bps
                  </td>
                  <td className="py-1 text-right font-mono">{r.fills}</td>
                  <td className={`py-1 text-right font-mono ${r.misses > 0 ? "text-warning" : ""}`}>
                    {r.misses}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-1.5 text-[10px] text-cyber-text-faint">
            Cost is measured against the price when the order was created; negative means it beat
            that price. Missed orders are charged a penalty, so a style that never fills does not
            look cheap.
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Why no order has reached the broker yet.
 *
 * Live routing is a chain of independent gates, every one of which fails
 * silently: keys, arm, a strategy set Live, an Alpaca-market universe, real
 * candles, an open session. Break any link and the symptom is identical — an
 * armed cockpit and an empty Alpaca dashboard — so the chain is laid out here
 * with the fix attached to whichever link is actually broken.
 */
function ReadinessCard() {
  const { live, strategies, barBacked, setStrategyState, passports } = useStore();

  // Only this strategy trades Alpaca markets today.
  const equityStrategies = strategies.filter((s) => s.venueClass === "alpaca");
  const liveEquity = equityStrategies.filter((s) => s.state === "live");
  const barsReady = equityStrategies.some((s) => s.universe.some((id) => barBacked.has(id)));
  // A strategy may only go live with a green Strategy Passport.
  const firstPassport = equityStrategies[0] ? passports.get(equityStrategies[0].id) : undefined;
  const canArmFirst = firstPassport?.liveReady ?? false;

  const steps = [
    {
      label: "Alpaca keys saved",
      ok: live.alpacaConnected,
      detail: live.alpacaConnected ? "in the OS keychain" : "Settings → Alpaca paper account",
    },
    {
      label: "Real equity candles loaded",
      ok: barsReady,
      detail: barsReady
        ? "indicators are running on real bars"
        : "waiting for Alpaca bars: strategies skip any market with under 30",
    },
    {
      label: "Live execution armed for Alpaca",
      ok: live.armed && live.venues.includes("alpaca"),
      detail: !live.armed
        ? "type ARM LIVE below"
        : live.venues.includes("alpaca")
          ? `routing to the ${live.paper ? "paper" : "LIVE"} endpoint`
          : "armed, but Alpaca is not an enabled venue: disarm, switch it on under Venues, re-arm",
    },
    {
      label: "A strategy set to Live",
      ok: liveEquity.length > 0,
      detail:
        liveEquity.length > 0
          ? liveEquity.map((s) => s.name).join(", ")
          : equityStrategies.length > 0
            ? canArmFirst
              ? `${equityStrategies[0].name} is ${equityStrategies[0].state}; only a Live strategy sends entries`
              : `${equityStrategies[0].name} has not earned live money yet (see its Strategy Passport on the Strategies page). To prove the pipeline without a strategy, use the connection test below.`
            : "no strategy trades Alpaca markets",
      fix:
        liveEquity.length === 0 && equityStrategies.length > 0 && canArmFirst
          ? {
              label: `Set ${equityStrategies[0].name} Live`,
              run: () => void setStrategyState(equityStrategies[0].id, "live").catch(() => undefined),
            }
          : undefined,
    },
    {
      label: "Market session open",
      ok: !live.blockedReason,
      detail: live.blockedReason ?? (live.armed ? "clear to trade" : "checked once armed"),
    },
  ];

  const done = steps.filter((s) => s.ok).length;

  return (
    <Card
      className="mb-4"
      title="Why no orders yet?"
      right={
        <Badge tone={done === steps.length ? "green" : "neutral"}>
          {done}/{steps.length} ready
        </Badge>
      }
    >
      <div className="space-y-1.5">
        {steps.map((s) => (
          <div key={s.label} className="flex items-start gap-2 text-sm">
            {s.ok ? (
              <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-success" />
            ) : (
              <Circle size={14} className="mt-0.5 shrink-0 text-cyber-text-faint" />
            )}
            <div className="flex-1">
              <span className={s.ok ? "text-cyber-text" : "text-cyber-text-dim"}>{s.label}</span>
              <div className="text-[11px] text-cyber-text-faint">{s.detail}</div>
            </div>
            {s.fix && (
              <Button tone="cyan" className="!px-2 !py-1" onClick={s.fix.run}>
                {s.fix.label}
              </Button>
            )}
          </div>
        ))}
      </div>
      {done === steps.length && (
        <div className="mt-3 text-[11px] text-success">
          Every gate is clear: the next signal on an Alpaca market routes to the broker.
        </div>
      )}
    </Card>
  );
}

/**
 * Per-market trace of the routing chain, straight from the engine.
 *
 * The readiness card above covers the global gates; this covers the per-market
 * ones the checklist can't see — no candles, already holding, already acted on
 * this bar, signal fighting the trend, or simply no signal yet. Between them
 * there is no state where "nothing is happening" has no explanation.
 */
function DiagnosticsCard() {
  const [rows, setRows] = useState<MarketDiag[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [testMsg, setTestMsg] = useState("");

  async function refresh() {
    setBusy(true);
    setErr("");
    try {
      setRows(await liveDiagnostics());
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    }
    setBusy(false);
  }

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 10_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function test(marketId: string) {
    setTestMsg("sending…");
    try {
      // 0 = the venue's minimum size: this proves the connection, not a strategy.
      setTestMsg(await sendTestOrder(marketId, 0));
    } catch (e) {
      setTestMsg(String(e instanceof Error ? e.message : e));
    }
    void refresh();
  }

  const clear = rows.filter((r) => !r.suppressed);

  return (
    <Card
      className="mb-4"
      title="Per-market trace"
      right={
        <Button tone="cyan" className="!px-2 !py-1" disabled={busy} onClick={() => void refresh()}>
          Refresh
        </Button>
      }
    >
      {err && <div className="mb-2 text-xs text-danger">{err}</div>}
      <div className="space-y-1.5">
        {rows.map((r) => (
          <div key={r.marketId} className="rounded border border-cyber-border bg-cyber-surface/40 px-2 py-1.5 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-cyber-text">{r.symbol}</span>
              <span className="text-cyber-text-faint">{r.price.toFixed(2)}</span>
              <Badge tone={r.barBacked ? "green" : "neutral"}>{r.bars} bars</Badge>
              {r.quoteAgeSec > 30 && <Badge tone="red">quote {r.quoteAgeSec}s old</Badge>}
              {r.hasPosition && <Badge tone="purple">holding</Badge>}
              <span className="flex-1" />
              <Button tone="purple" className="!px-2 !py-0.5" onClick={() => void test(r.marketId)}>
                Connection test
              </Button>
            </div>
            {r.signal && <div className="mt-1 text-success">signal · {r.signal}</div>}
            <div className={`mt-0.5 ${r.suppressed ? "text-warning" : "text-success"}`}>
              {r.suppressed ?? "Clear: the next signal routes to the broker"}
            </div>
          </div>
        ))}
        {rows.length === 0 && !err && (
          <div className="text-xs text-cyber-text-faint">No Alpaca markets in the engine yet.</div>
        )}
      </div>
      {testMsg && <div className="mt-2 text-xs text-cyber-text-dim">{testMsg}</div>}
      <div className="mt-2 text-[11px] text-cyber-text-faint">
        {clear.length} of {rows.length} markets are clear to route. <b>Connection test</b> sends one buy at the
        venue's minimum size through the full path (risk manager, broker, fill), so a wrong key or a closed session
        surfaces immediately. It is a connection test, not a strategy: it needs no Strategy Passport, it is the
        only order that skips one, and no strategy is set live by it.
      </div>
    </Card>
  );
}

function Field({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-widest text-cyber-text-faint">{label}</div>
      <div className={`text-sm font-bold ${good ? "text-success" : "text-cyber-text"}`}>{value}</div>
    </div>
  );
}

function fmt(v: string): string {
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : v;
}
