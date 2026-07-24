import { useEffect, useState } from "react";
import { Radio, ShieldAlert, Power, PlugZap, TriangleAlert, CheckCircle2, Circle, DollarSign } from "lucide-react";
import { Card, PageHeader, Badge, Button, Toggle } from "../components/ui";
import { useStore } from "../store";
import {
  liveMode,
  alpacaAccount,
  setLiveConfig,
  liveDiagnostics,
  sendTestOrder,
  type AlpacaAccount,
  type MarketDiag,
} from "../live";

const ARM_PHRASE = "ARM LIVE";

export function Live() {
  const { live } = useStore();
  const mode = liveMode();
  const [paper, setPaper] = useState(true);
  const [dryRun, setDryRun] = useState(false);
  const [extendedHours, setExtendedHours] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [acct, setAcct] = useState<AlpacaAccount | null>(null);
  const [acctErr, setAcctErr] = useState("");

  // Reflect the engine's actual arm config once it reports back.
  useEffect(() => {
    if (live.armed) {
      setPaper(live.paper);
      setDryRun(live.dryRun);
      setExtendedHours(live.extendedHours);
    }
  }, [live.armed, live.paper, live.dryRun, live.extendedHours]);

  async function testConn() {
    setBusy(true);
    setAcct(null);
    setAcctErr("");
    try {
      setAcct(await alpacaAccount(paper));
    } catch (e) {
      setAcctErr(String(e instanceof Error ? e.message : e));
    }
    setBusy(false);
  }

  async function arm() {
    setBusy(true);
    setMsg("");
    try {
      await setLiveConfig(true, paper, dryRun, extendedHours);
      setConfirm("");
      setMsg("armed");
    } catch (e) {
      setMsg(String(e instanceof Error ? e.message : e));
    }
    setBusy(false);
  }
  async function disarm() {
    setBusy(true);
    setMsg("");
    try {
      await setLiveConfig(false, paper, dryRun, extendedHours);
      setMsg("disarmed");
    } catch (e) {
      setMsg(String(e instanceof Error ? e.message : e));
    }
    setBusy(false);
  }

  if (mode === "none") {
    return (
      <div className="animate-fade-in max-w-3xl">
        <PageHeader title="Live Execution" subtitle="Route real orders — gated, paper-first" />
        <Card className="border-warning/30 bg-warning/5">
          <div className="flex items-start gap-3">
            <TriangleAlert size={18} className="mt-0.5 shrink-0 text-warning" />
            <div className="text-sm text-cyber-text-dim">
              <div className="font-bold text-warning">Not available in the browser paper build</div>
              Live execution needs a broker connection. Run the <span className="text-accent">desktop app</span>{" "}
              (Alpaca keys in the OS keychain) or a <span className="text-accent">backend server</span> (keys in its
              environment).
            </div>
          </div>
        </Card>
      </div>
    );
  }

  const canArm = confirm.trim().toUpperCase() === ARM_PHRASE && !live.armed;
  const realMoney = live.armed && !live.paper && !live.dryRun;

  return (
    <div className="animate-fade-in max-w-3xl">
      <PageHeader title="Live Execution" subtitle="Alpaca equities · paper-first · fully gated" />

      {/* status banner */}
      {live.armed ? (
        <div
          className={`mb-4 flex items-center justify-between rounded-lg border px-4 py-2 text-sm font-bold ${
            realMoney
              ? "border-danger/50 bg-danger/15 text-danger text-glow-red animate-pulse-red"
              : "border-warning/40 bg-warning/10 text-warning"
          }`}
        >
          <span className="flex items-center gap-2">
            <Radio size={15} /> LIVE ARMED —{" "}
            {live.dryRun ? "dry-run (nothing sent)" : live.paper ? "paper endpoint (no real money)" : "REAL MONEY"}
          </span>
          <span className="text-xs">{live.pending} pending</span>
        </div>
      ) : (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-accent/20 bg-accent/5 px-4 py-2 text-sm text-accent">
          <Power size={14} /> Disarmed — everything simulates. No order leaves this machine.
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
              Exits are never blocked — an open position can always be closed.
            </div>
          </div>
        </div>
      )}

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
            <span className="text-accent">Alpaca</span> market are sent to the broker. Everything else stays paper.
            The global kill switch and every risk limit still apply to each order. Start on the{" "}
            <span className="text-accent">paper endpoint</span> (real API, fake money); flip to real money only once
            you trust it. Not financial advice — read SAFETY.md.
          </div>
        </div>
      </Card>

      {/* connection test */}
      <Card
        title="1 · Connection"
        className="mb-4"
        right={<Badge tone={live.alpacaConnected ? "green" : "neutral"}>{live.alpacaConnected ? "keys present" : "check keys"}</Badge>}
      >
        <div className="mb-3 text-sm text-cyber-text-dim">
          Verify your Alpaca keys reach the {paper ? "paper" : "live"} endpoint before arming. Read-only — places no
          order.{" "}
          {mode === "native"
            ? `Uses the ${paper ? "Alpaca — Paper" : "Alpaca — Live"} keys from Settings; the two accounts have separate key pairs.`
            : "Keys come from the server env (APCA_API_KEY_ID / APCA_API_SECRET_KEY, or APCA_LIVE_* for the live endpoint)."}
        </div>
        <Button tone="cyan" icon={PlugZap} disabled={busy} onClick={testConn}>
          Test {paper ? "paper" : "live"} connection
        </Button>
        {acct && (
          <div className="mt-3 grid grid-cols-2 gap-3 rounded-lg border border-cyber-border bg-cyber-surface/50 p-3 text-sm sm:grid-cols-4">
            <Field label="Status" value={acct.status} good={acct.status === "ACTIVE"} />
            <Field label="Endpoint" value={acct.paper ? "paper" : "live"} good={acct.paper} />
            <Field label="Buying power" value={`$${fmt(acct.buyingPower)}`} />
            <Field label="Cash" value={`$${fmt(acct.cash)}`} />
          </div>
        )}
        {acctErr && <div className="mt-2 text-xs text-danger">{acctErr}</div>}
      </Card>

      {/* arm */}
      <Card title="2 · Arm" right={<DollarSign size={14} className="text-danger" />}>
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
                  ? "locked while armed — disarm to change"
                  : paper
                    ? "paper — no real money"
                    : "LIVE — real money"}
              </div>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className={paper ? "text-accent" : "text-danger"}>{paper ? "Paper" : "Live"}</span>
              <Toggle on={!paper} onChange={(v) => !live.armed && setPaper(!v)} />
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
                {live.armed ? "locked while armed — disarm to change" : "log intended orders, submit nothing"}
              </div>
            </div>
            <Toggle on={dryRun} onChange={(v) => !live.armed && setDryRun(v)} />
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
                ? "locked while armed — disarm to change"
                : live.broker?.extendedOpen && !live.broker?.marketOpen
                  ? `pre/after-market is open right now${live.broker.sessionEnd ? ` until ${live.broker.sessionEnd} ET` : ""} — thin book, wide spreads`
                  : "trade 04:00–20:00 ET instead of 09:30–16:00 · whole-share limit orders only"}
            </div>
          </div>
          <Toggle on={extendedHours} onChange={(v) => !live.armed && setExtendedHours(v)} />
        </div>

        {/* Switching to real money is a different decision from arming at all. */}
        {!live.armed && !paper && !dryRun && (
          <div className="mb-3 flex items-start gap-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm">
            <TriangleAlert size={15} className="mt-0.5 shrink-0 text-danger" />
            <div className="text-cyber-text-dim">
              <span className="font-bold text-danger">Real money.</span> Arming now routes orders to your live
              Alpaca account. This uses the <span className="text-accent">Alpaca — Live</span> keys from Settings,
              not the paper ones — test them there first if you haven't.
            </div>
          </div>
        )}

        {!live.armed ? (
          <>
            <div className="mb-2 text-sm text-cyber-text-dim">
              Type <span className="font-bold text-danger">{ARM_PHRASE}</span> to enable order routing
              {!paper && !dryRun ? " with REAL MONEY" : ""}.
            </div>
            <div className="flex items-center gap-2">
              <input
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder={ARM_PHRASE}
                className="w-40 rounded border border-cyber-border bg-cyber-surface px-2 py-1.5 text-sm focus:border-danger focus:outline-none"
              />
              <Button tone="red" icon={Radio} disabled={!canArm || busy} onClick={arm}>
                Arm live
              </Button>
              {msg && <span className="text-xs text-cyber-text-dim">{msg}</span>}
            </div>
          </>
        ) : (
          <div className="flex items-center gap-2">
            <Button tone="cyan" icon={Power} disabled={busy} onClick={disarm}>
              Disarm — back to paper
            </Button>
            {msg && <span className="text-xs text-cyber-text-dim">{msg}</span>}
          </div>
        )}

        <div className="mt-4 space-y-1 text-[11px] leading-snug text-cyber-text-faint">
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> Only <b>Alpaca</b> markets route live — crypto &amp; Polymarket always paper here.</div>
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> Only strategies set to <b>Live</b> (Strategies page) send entries; a position opened live also exits live.</div>
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> The kill switch, daily-loss, drawdown &amp; position caps gate every order first.</div>
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> Entries are refused while the market is closed, the account is restricted, or the broker check is stale — exits never are.</div>
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> Orders go out as marketable limits, so a thin or gapped book can't fill you at any price.</div>
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> An order that doesn't fill is cancelled, then re-read — nothing is ever left working after Pythia gives up on it.</div>
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> Positions are reconciled against Alpaca every few minutes; the broker is always treated as the source of truth.</div>
        </div>
      </Card>
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
  const { live, strategies, barBacked, setStrategyState } = useStore();

  // Only this strategy trades Alpaca markets today.
  const equityStrategies = strategies.filter((s) => s.venueClass === "alpaca");
  const liveEquity = equityStrategies.filter((s) => s.state === "live");
  const barsReady = equityStrategies.some((s) => s.universe.some((id) => barBacked.has(id)));

  const steps = [
    {
      label: "Alpaca keys saved",
      ok: live.alpacaConnected,
      detail: live.alpacaConnected ? "in the OS keychain" : "Settings → Alpaca — Paper",
    },
    {
      label: "Real equity candles loaded",
      ok: barsReady,
      detail: barsReady
        ? "indicators are running on real bars"
        : "waiting for Alpaca bars — strategies skip any market with under 30",
    },
    {
      label: "Live execution armed",
      ok: live.armed,
      detail: live.armed ? `routing to the ${live.paper ? "paper" : "LIVE"} endpoint` : "type ARM LIVE below",
    },
    {
      label: "A strategy set to Live",
      ok: liveEquity.length > 0,
      detail:
        liveEquity.length > 0
          ? liveEquity.map((s) => s.name).join(", ")
          : equityStrategies.length > 0
            ? `${equityStrategies[0].name} is ${equityStrategies[0].state} — only a Live strategy sends entries`
            : "no strategy trades Alpaca markets",
      fix:
        liveEquity.length === 0 && equityStrategies.length > 0
          ? { label: `Set ${equityStrategies[0].name} Live`, run: () => setStrategyState(equityStrategies[0].id, "live") }
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
          Every gate is clear — the next signal on an Alpaca market routes to the broker.
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
      setTestMsg(await sendTestOrder(marketId, 250));
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
                Test $250
              </Button>
            </div>
            {r.signal && <div className="mt-1 text-success">signal · {r.signal}</div>}
            <div className={`mt-0.5 ${r.suppressed ? "text-warning" : "text-success"}`}>
              {r.suppressed ?? "clear — the next signal routes to the broker"}
            </div>
          </div>
        ))}
        {rows.length === 0 && !err && (
          <div className="text-xs text-cyber-text-faint">No Alpaca markets in the engine yet.</div>
        )}
      </div>
      {testMsg && <div className="mt-2 text-xs text-cyber-text-dim">{testMsg}</div>}
      <div className="mt-2 text-[11px] text-cyber-text-faint">
        {clear.length} of {rows.length} markets are clear to route. <b>Test $250</b> sends one real order through the
        full path — risk manager, broker, fill — so a wrong key or a closed session surfaces immediately.
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
