import { useEffect, useState } from "react";
import { Radio, ShieldAlert, Power, PlugZap, TriangleAlert, CheckCircle2, DollarSign } from "lucide-react";
import { Card, PageHeader, Badge, Button, Toggle } from "../components/ui";
import { useStore } from "../store";
import { liveMode, alpacaAccount, setLiveConfig, type AlpacaAccount } from "../live";

const ARM_PHRASE = "ARM LIVE";

export function Live() {
  const { live } = useStore();
  const mode = liveMode();
  const [paper, setPaper] = useState(true);
  const [dryRun, setDryRun] = useState(false);
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
    }
  }, [live.armed, live.paper, live.dryRun]);

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
      await setLiveConfig(true, paper, dryRun);
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
      await setLiveConfig(false, paper, dryRun);
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
          order. {mode === "native" ? "Keys come from the OS keychain (Settings → Alpaca)." : "Keys come from the server env (APCA_API_KEY_ID / APCA_API_SECRET_KEY)."}
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
          <div className="flex items-center justify-between rounded-lg border border-cyber-border bg-cyber-surface/40 px-3 py-2">
            <div>
              <div className="text-sm font-medium">Endpoint</div>
              <div className="text-[11px] text-cyber-text-faint">{paper ? "paper — no real money" : "LIVE — real money"}</div>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className={paper ? "text-accent" : "text-danger"}>{paper ? "Paper" : "Live"}</span>
              <Toggle on={!paper} onChange={(v) => setPaper(!v)} />
            </div>
          </div>
          <div className="flex items-center justify-between rounded-lg border border-cyber-border bg-cyber-surface/40 px-3 py-2">
            <div>
              <div className="text-sm font-medium">Dry-run</div>
              <div className="text-[11px] text-cyber-text-faint">log intended orders, submit nothing</div>
            </div>
            <Toggle on={dryRun} onChange={setDryRun} />
          </div>
        </div>

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
