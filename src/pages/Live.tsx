import { useEffect, useState } from "react";
import {
  Radio,
  ShieldAlert,
  Power,
  PlugZap,
  TriangleAlert,
  CheckCircle2,
  DollarSign,
  Timer,
} from "lucide-react";
import { Card, PageHeader, Badge, Button, Toggle } from "../components/ui";
import { useStore } from "../store";
import { liveMode, alpacaAccount, setLiveConfig, verifyVenue, type AlpacaAccount } from "../live";
import type { Venue } from "../types";

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
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [acct, setAcct] = useState<AlpacaAccount | null>(null);
  const [checks, setChecks] = useState<Record<string, string>>({});

  // Reflect the engine's actual arm config once it reports back.
  useEffect(() => {
    if (live.armed) {
      setPaper(live.paper);
      setDryRun(live.dryRun);
      setVenues(live.venues);
      setTimeoutSec(live.timeoutSec);
    }
  }, [live.armed, live.paper, live.dryRun, live.venues, live.timeoutSec]);

  function toggleVenue(v: Venue, on: boolean) {
    setVenues((prev) => (on ? [...new Set([...prev, v])] : prev.filter((x) => x !== v)));
  }

  async function testConn() {
    setBusy(true);
    setAcct(null);
    setErr("");
    const next: Record<string, string> = {};
    for (const v of venues) {
      try {
        next[v] = await verifyVenue(v, paper);
      } catch (e) {
        next[v] = `❌ ${e instanceof Error ? e.message : String(e)}`;
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
      await setLiveConfig({ armed: true, paper, dryRun, venues, timeoutSec });
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
      await setLiveConfig({ armed: false, paper, dryRun, venues, timeoutSec });
      setMsg("disarmed");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
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
              Live execution needs a venue connection. Run the <span className="text-accent">desktop app</span>{" "}
              (keys in the OS keychain) or a <span className="text-accent">backend server</span> (keys in its
              environment).
            </div>
          </div>
        </Card>
      </div>
    );
  }

  const canArm = confirm.trim().toUpperCase() === ARM_PHRASE && !live.armed && venues.length > 0;
  const realMoney = live.armed && !live.paper && !live.dryRun;

  return (
    <div className="animate-fade-in max-w-3xl">
      <PageHeader title="Live Execution" subtitle="Per-venue arming · paper-first · fully gated" />

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
            {live.venues.length > 0 && (
              <span className="font-normal opacity-80">· {live.venues.join(", ")}</span>
            )}
          </span>
          <span className="text-xs">{live.pending} pending</span>
        </div>
      ) : (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-accent/20 bg-accent/5 px-4 py-2 text-sm text-accent">
          <Power size={14} /> Disarmed — everything simulates. No order leaves this machine.
        </div>
      )}

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

      <Card className="mb-4 border-danger/30 bg-danger/5">
        <div className="flex items-start gap-3">
          <ShieldAlert size={18} className="mt-0.5 shrink-0 text-danger" />
          <div className="text-sm text-cyber-text-dim">
            <div className="font-bold text-danger text-glow-red">Real orders, real risk</div>
            When armed, orders from a <span className="text-accent">Live</span>-state strategy on an{" "}
            <span className="text-accent">enabled venue</span> are sent for real. Everything else stays paper. The
            global kill switch and every risk limit still gate each order. Start on the{" "}
            <span className="text-accent">paper endpoint</span> (real API, fake money); flip to real money only once
            you trust it. Not financial advice — read SAFETY.md.
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
                    {connected ? note : "no keys — add them in Settings"}
                  </div>
                </div>
                <Toggle
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
          Verify your keys reach the {paper ? "paper" : "live"} endpoint before arming. Read-only — places no order.{" "}
          {mode === "native"
            ? "Keys come from the OS keychain (Settings)."
            : "Keys come from the server environment."}
        </div>
        <Button tone="cyan" icon={PlugZap} disabled={busy || venues.length === 0} onClick={testConn}>
          Test {paper ? "paper" : "live"} connection
        </Button>
        {Object.entries(checks).length > 0 && (
          <div className="mt-3 space-y-1 rounded-lg border border-cyber-border bg-cyber-surface/50 p-3 text-xs">
            {Object.entries(checks).map(([v, r]) => (
              <div key={v} className={r.startsWith("❌") ? "text-danger" : "text-success"}>
                <span className="uppercase tracking-widest text-cyber-text-faint">{v}</span> — {r}
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
          <div className="flex items-center justify-between rounded-lg border border-cyber-border bg-cyber-surface/40 px-3 py-2 sm:col-span-2">
            <div>
              <div className="flex items-center gap-1.5 text-sm font-medium">
                <Timer size={13} /> Order timeout
              </div>
              <div className="text-[11px] text-cyber-text-faint">
                after this long, an unfilled order is <b>cancelled at the venue</b> and whatever filled is booked
              </div>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <input
                type="range"
                min={15}
                max={900}
                step={15}
                value={timeoutSec}
                onChange={(e) => setTimeoutSec(Number(e.target.value))}
                className="w-32 accent-accent"
              />
              <span className="w-12 text-right font-mono">{timeoutSec}s</span>
            </div>
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
            {venues.length === 0 && (
              <div className="mt-2 text-xs text-warning">Enable at least one venue above.</div>
            )}
          </>
        ) : (
          <div className="flex items-center gap-2">
            <Button tone="cyan" icon={Power} disabled={busy} onClick={disarm}>
              Disarm — back to paper
            </Button>
            {msg && <span className="text-xs text-cyber-text-dim">{msg}</span>}
          </div>
        )}
        {err && <div className="mt-2 text-xs text-danger">{err}</div>}

        <div className="mt-4 space-y-1 text-[11px] leading-snug text-cyber-text-faint">
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> Arming runs a read-only key check first and refuses if a venue does not answer.</div>
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> Only strategies set to <b>Live</b> (Strategies page) send entries; a position opened live also exits live.</div>
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> The kill switch, daily-loss, drawdown &amp; position caps gate every order first.</div>
          <div className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-success" /> Orders that cannot fill (market closed, no buying power) are refused before submission, not left hanging.</div>
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
