import { useEffect, useState, type ReactNode } from "react";
import { Radio, Power, PlugZap, TriangleAlert, CheckCircle2, XCircle, Lock, RefreshCw } from "lucide-react";
import { Badge, Button, Card, List, Notice, Page, Toggle, changeTone, inputCls, money, signedMoney } from "../design";
import { KeyStats, More, Nothing, Row, Section, SwitchRow, plural } from "../pagekit";
import {
  amountText,
  canArmNow,
  liveMood,
  liveMoodWords,
  readyCount,
  realExposure,
  secondsSince,
  signedBps,
} from "../pagekit/money";
import { useStore } from "../store";
import { DataHealthCard } from "../components/DataHealth";
import {
  liveMode,
  alpacaAccount,
  setLiveConfig,
  verifyVenue,
  liveDiagnostics,
  sendTestOrder,
  setMakerRoute,
  type AlpacaAccount,
  type MarketDiag,
} from "../live";
import type { Venue } from "../types";
import { cryptoDemoName, demoApiTestNote, demoIsApiTestOnly } from "../venueNames";
import { PAIR_STATUS, estimatedFeeTotal, pairsToShow, qty9, reconcileHeadline } from "../demoReconcile";
import { changeStrategyState } from "../strategyState";
import { ALPACA_CRYPTO_DEMO, alpacaMaker, alpacaMakerStats, makerSummary, makerWindowLine } from "../lib/maker";

const ARM_PHRASE = "ARM LIVE";

/** Venues that have an implemented order path. Polymarket is read-only. */
const ROUTABLE: { venue: Venue; label: string; note: string }[] = [
  { venue: "alpaca", label: "Alpaca · equities", note: "US market hours" },
  { venue: "crypto", label: "Crypto exchange", note: "24/7 spot, long only" },
];

/** What arming and routing promise, shown under the arm step. */
const GUARANTEES: ReactNode[] = [
  "Arming runs a read-only key check first and refuses if a venue does not answer.",
  <>
    Only strategies set to <b>Live</b> (Strategies page) send entries; a position opened live also exits live.
  </>,
  "The kill switch, daily-loss, drawdown and position caps gate every order first.",
  "Orders that cannot fill (market closed, no buying power) are refused before submission, not left hanging.",
  "Alpaca entries are refused while the market is closed, the account is restricted, or the broker check is stale. Exits never are.",
  "Whole-share Alpaca orders go out as marketable limits, so a thin or gapped book can't fill them at any price.",
  "An order that doesn't fill is cancelled at the venue, then re-read, so nothing is ever left working after Pythia gives up on it.",
  "Positions are reconciled against the broker every couple of minutes while armed; the broker is always treated as the source of truth.",
];

export function Live() {
  const { live, positions } = useStore();
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
      <Page title="Live trading" subtitle="Send real orders to a broker: gated, and paper first.">
        <Card>
          <Nothing icon={Radio} title="Live trading needs the desktop app or a connected server">
            Real orders need a connection to a broker. Use the desktop app (keys in the OS keychain) or a backend server
            (keys in its environment). This browser version can only practise.
          </Nothing>
        </Card>
      </Page>
    );
  }

  const canArm = canArmNow(confirm, ARM_PHRASE, live.armed, venues.length);
  const state = liveMood(live);
  const realMoney = state === "real";
  const words = liveMoodWords(state);
  const exposure = realExposure(positions);
  const aboutToArmReal = !live.armed && !paper && !dryRun;

  return (
    <Page
      title="Live trading"
      subtitle="Send real orders to a broker. Each venue is armed on its own, paper endpoint first, and every order still passes the risk limits."
    >
      {/* Where orders go right now. Real money is the loudest state on the page. */}
      {live.armed ? (
        <Notice
          tone={realMoney ? "danger" : "warning"}
          icon={Radio}
          title={`Armed: ${live.dryRun ? "dry-run, nothing is sent" : live.paper ? "paper endpoint, no real money" : "real money"}`}
        >
          {realMoney ? "Orders from Live strategies are sent to your live account and spend real money. " : ""}
          {live.venues.length > 0 ? `Venues: ${live.venues.join(", ")}. ` : ""}
          <span className="tabular">{plural(live.pending, "order")} pending.</span>
        </Notice>
      ) : (
        <Notice tone="success" icon={Power} title="Disarmed">
          Everything is simulated. No order leaves this machine.
        </Notice>
      )}

      <KeyStats
        items={[
          {
            label: "Live trading",
            value: words.value,
            sub: (
              <span className="flex flex-wrap items-center gap-1.5">
                <Badge tone={realMoney ? "bad" : state === "off" ? "good" : "warn"}>{words.badge}</Badge>
                <span>{words.detail}</span>
              </span>
            ),
            help: "Armed means orders from strategies set to Live are sent to the broker. Off means everything is simulated.",
          },
          {
            label: "Real money at risk",
            value: money(exposure.value),
            sub: exposure.count > 0 ? `${plural(exposure.count, "real position")} at the venue` : "No real positions open",
            help: "What the positions bought with real money are worth at the last price.",
          },
          {
            label: "Real positions now",
            value: signedMoney(exposure.unrealized),
            tone: changeTone(exposure.unrealized),
            sub: "gain or loss if they were sold now",
            help: "The open result of the positions bought with real money, before costs to close them.",
          },
        ]}
      />

      {/* Real positions cannot be closed by the simulator, so this is not a detail. */}
      {live.livePositions > 0 && !live.armed && (
        <Notice tone="danger" title={`${plural(live.livePositions, "real position")} still open at the venue`}>
          Disarming does not close them, and stop-losses cannot fire while disarmed. Re-arm to manage them from here, or
          flatten them in the venue's own dashboard.
        </Notice>
      )}

      {/*
        The most confusing state to be in is "armed, and nothing is happening".
        Almost always it is one of: the market is closed, the account is
        restricted, the day-trade ceiling is reached, or the broker check has
        not landed yet. The engine already knows which, so say it plainly here
        rather than leaving the user to guess from an empty order book.
      */}
      {live.armed && live.blockedReason && (
        <Notice tone="warning" title="New entries are on hold">
          {live.blockedReason}
          <span className="mt-1 block text-[13px]">Exits are never blocked: an open position can always be closed.</span>
        </Notice>
      )}

      <ReadinessCard />

      {live.broker && (
        <Section title="Broker session" hint="What the broker says about the market and your account.">
          <List>
            <Row
              label="US market"
              value={<Badge tone={live.broker.marketOpen ? "good" : "neutral"}>{live.broker.marketOpen ? "Open" : "Closed"}</Badge>}
              sub={!live.broker.marketOpen && live.broker.nextOpen ? `Next open: ${live.broker.nextOpen}` : undefined}
            />
            <Row label="Equity" value={money(live.broker.equity)} />
            <Row label="Buying power" value={money(live.broker.buyingPower)} />
            <Row
              label="Day-trade cap"
              value={
                <Badge tone={live.broker.dayTradeLimitReached ? "bad" : "good"}>{live.broker.dayTradeLimitReached ? "Reached" : "Clear"}</Badge>
              }
            />
          </List>
          {live.broker.restricted && (
            <Notice tone="danger" className="mt-2" title="Account restricted">
              {live.broker.restricted}
            </Notice>
          )}
          <p className="mt-2 text-[13px] text-faint">
            Checked {secondsSince(live.broker.checkedAt, Date.now())}s ago · live entries block once this is over 5 minutes old.
          </p>
        </Section>
      )}

      <Notice tone="danger" title="Real orders, real risk">
        When armed, orders from a <b>Live</b>-state strategy on an <b>enabled venue</b> are sent for real. Everything else
        stays paper. The global kill switch and every risk limit still gate each order. Start on the{" "}
        <b>paper endpoint</b> (real API, fake money); flip to real money only once you trust it. Not financial advice:
        read SAFETY.md.
      </Notice>

      <Section
        title="Step 1: Venues"
        help="Where orders can go. Each venue is armed on its own."
        hint="Each venue is armed separately. A venue you leave off keeps simulating even while the rest are live."
      >
        <List>
          {ROUTABLE.map(({ venue, label, note }) => {
            const connected = live.connected.includes(venue);
            return (
              <div key={venue} className="flex items-center justify-between gap-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="text-[15px] font-semibold text-ink">{label}</div>
                  <div className="text-[13px] text-muted">{connected ? note : "No keys yet: add them in Settings"}</div>
                </div>
                <Toggle label={`Arm ${label}`} on={venues.includes(venue)} onChange={(v) => toggleVenue(venue, v)} />
              </div>
            );
          })}
        </List>
        <p className="mt-2 text-[13px] text-faint">Polymarket is not listed: its odds are read-only and it never routes an order.</p>
      </Section>

      <Section
        title="Step 2: Connection"
        help="A read-only check that your keys reach the broker. It places no order."
        hint={
          <>
            Check that your keys reach the {paper ? "paper" : "live"} endpoint before arming. Read-only: it places no
            order.{" "}
            {mode === "native"
              ? `Keys come from the OS keychain (Settings). Alpaca uses the ${paper ? "Alpaca paper account" : "Alpaca live account"} keys; the two accounts have separate key pairs.`
              : "Keys come from the server environment (Alpaca: APCA_API_KEY_ID / APCA_API_SECRET_KEY, or APCA_LIVE_* for the live endpoint)."}
          </>
        }
        right={
          <Badge tone={live.connected.length > 0 ? "good" : "neutral"}>
            {live.connected.length > 0 ? `${live.connected.length} connected` : "Check keys"}
          </Badge>
        }
      >
        <Button variant="secondary" icon={PlugZap} disabled={busy || venues.length === 0} onClick={testConn}>
          Test {paper ? "paper" : "live"} connection
        </Button>
        {Object.entries(checks).length > 0 && (
          <List className="mt-3">
            {Object.entries(checks).map(([v, r]) => (
              <div key={v} className="py-3">
                <Outcome ok={r.ok} okWord="Works" failWord="Failed">
                  <span className="font-semibold text-ink">{venueName(v)}.</span> {r.text}
                </Outcome>
              </div>
            ))}
          </List>
        )}
        {acct && (
          <List className="mt-3">
            <Row label="Status" value={<Badge tone={acct.status === "ACTIVE" ? "good" : "warn"}>{acct.status}</Badge>} />
            <Row label="Endpoint" value={acct.paper ? <Badge tone="accent">Paper</Badge> : <Badge tone="bad">Live: real money</Badge>} />
            <Row label="Buying power" value={amountText(acct.buyingPower)} />
            <Row label="Day trades" value={String(acct.daytradeCount ?? 0)} />
          </List>
        )}
      </Section>

      <Section title="Step 3: Arm" help="Turn on real order routing for the venues above." hint="Pick where orders go, then type the phrase to arm.">
        {/*
          The endpoint, dry-run and extended-hours switches are inert while
          armed, and are shown that way. `setLiveConfig` is only sent by arm(),
          so flipping these mid-flight changed a local value and nothing else:
          the switch moved, the label said "Paper", and orders kept going to the
          live endpoint. Requiring a disarm to change endpoint is also the right
          safety behaviour: moving between fake and real money should be a
          deliberate re-arm, not a tap.
        */}
        <List>
          <LockRow
            label="Endpoint"
            locked={live.armed}
            hint={paper ? "Paper: no real money" : "Live: real money"}
            control={
              <div className="flex items-center gap-2">
                {paper ? <Badge tone="accent">Paper</Badge> : <Badge tone="bad">Live</Badge>}
                <Toggle
                  label="Use the live (real money) endpoint"
                  on={!paper}
                  disabled={live.armed}
                  onChange={(v) => !live.armed && setPaper(!v)}
                />
              </div>
            }
          />
          <LockRow
            label="Dry-run"
            locked={live.armed}
            hint="Write down the orders it would send, send nothing"
            control={<Toggle label="Dry-run" on={dryRun} disabled={live.armed} onChange={(v) => !live.armed && setDryRun(v)} />}
          />
          {/*
            Extended hours is the difference between "it trades" and "it trades
            only between 15:30 and 22:00 CEST". Off by default: the session is
            thin, spreads are wide, and no strategy here was validated on it.
          */}
          <LockRow
            label="Extended hours"
            locked={live.armed}
            hint={
              live.broker?.extendedOpen && !live.broker?.marketOpen
                ? `Pre/after-market is open right now${live.broker.sessionEnd ? ` until ${live.broker.sessionEnd} ET` : ""}: few buyers and sellers, wide spreads`
                : "Trade 04:00 to 20:00 ET instead of 09:30 to 16:00 · whole-share limit orders only"
            }
            control={
              <Toggle label="Extended hours" on={extendedHours} disabled={live.armed} onChange={(v) => !live.armed && setExtendedHours(v)} />
            }
          />
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3">
            <div className="min-w-0 flex-1 basis-48">
              <div className="text-[15px] font-semibold text-ink">Order timeout</div>
              <div className="text-[13px] leading-snug text-muted">
                After this long, an unfilled order is <b>cancelled at the venue</b> and whatever filled is booked.
              </div>
            </div>
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={15}
                max={900}
                step={15}
                value={timeoutSec}
                aria-label="Order timeout in seconds"
                onChange={(e) => setTimeoutSec(Number(e.target.value))}
                className="w-32"
                style={{ accentColor: "var(--color-accent)" }}
              />
              <span className="tabular w-12 text-right text-[15px] font-semibold text-ink">{timeoutSec}s</span>
            </div>
          </div>
        </List>

        {/* Switching to real money is a different decision from arming at all. */}
        {aboutToArmReal && (
          <Notice tone="danger" className="mt-3" title="Real money.">
            Arming now routes orders to your live Alpaca account. This uses the <b>Alpaca live account</b> keys from
            Settings, not the paper ones. Test them there first if you have not.
          </Notice>
        )}

        <div className="mt-4 border-t border-line pt-4">
          {!live.armed ? (
            <>
              <label htmlFor="arm-phrase" className="mb-2 block text-[15px] text-ink">
                Type <b className="text-down">{ARM_PHRASE}</b> to enable order routing
                {aboutToArmReal ? (
                  <>
                    {" "}
                    with <b className="text-down">REAL MONEY</b>
                  </>
                ) : (
                  ""
                )}
                .
              </label>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  id="arm-phrase"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  placeholder={ARM_PHRASE}
                  aria-label={`Type ${ARM_PHRASE} to confirm`}
                  spellCheck={false}
                  autoComplete="off"
                  className={`${inputCls} w-40`}
                />
                <Button variant="danger" icon={Radio} disabled={!canArm || busy} onClick={arm}>
                  Arm live
                </Button>
                {msg && (
                  <span role="status" className="text-[13px] text-muted">
                    {msg}
                  </span>
                )}
              </div>
              {venues.length === 0 && <p className="mt-2 text-[13px] text-warn">Enable at least one venue above.</p>}
            </>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="primary" icon={Power} disabled={busy} onClick={disarm}>
                Disarm: back to paper
              </Button>
              {msg && (
                <span role="status" className="text-[13px] text-muted">
                  {msg}
                </span>
              )}
            </div>
          )}
          {err && (
            <Notice tone="danger" className="mt-3" title="That did not work">
              {err}
            </Notice>
          )}
        </div>

        <div className="mt-4 border-t border-line pt-3">
          <div className="text-[15px] font-semibold text-ink">What protects every order</div>
          <ul className="mt-1 divide-y divide-line">
            {GUARANTEES.map((g, i) => (
              <li key={i} className="flex items-start gap-2.5 py-2.5 text-[13px] leading-snug text-muted">
                <CheckCircle2 size={16} aria-hidden className="mt-px shrink-0 text-up" />
                <span className="min-w-0">{g}</span>
              </li>
            ))}
          </ul>
        </div>
      </Section>

      <ExecutionPolicyCard />
      <DiagnosticsCard />
      <DataHealthCard />
      <DemoCard />
      <PaperReconcileCard />
    </Page>
  );
}

function venueName(v: string): string {
  return ROUTABLE.find((r) => r.venue === v)?.label ?? v;
}

/**
 * A pass or fail line: an icon, the word, and the message. Colour is never
 * the only signal. `soft` shows a failure as a caution (amber) rather than an
 * error (red).
 */
function Outcome({
  ok,
  okWord = "Done",
  failWord = "Failed",
  soft,
  children,
}: {
  ok: boolean;
  okWord?: string;
  failWord?: string;
  soft?: boolean;
  children: ReactNode;
}) {
  const Icon = ok ? CheckCircle2 : soft ? TriangleAlert : XCircle;
  const tone = ok ? "text-up" : soft ? "text-warn" : "text-down";
  return (
    <div className="flex items-start gap-2 text-[13px] leading-snug text-muted">
      <Icon size={16} aria-hidden className={`mt-px shrink-0 ${tone}`} />
      <div className="min-w-0 break-words">
        <span className={`font-semibold ${tone}`}>{ok ? okWord : failWord}:</span> {children}
      </div>
    </div>
  );
}

/** A setting that cannot change while armed: dimmed, with the lock said in words. */
function LockRow({ label, hint, locked, control }: { label: string; hint: ReactNode; locked: boolean; control: ReactNode }) {
  return (
    <div className={`flex items-center justify-between gap-4 py-3 ${locked ? "opacity-60" : ""}`}>
      <div className="min-w-0 flex-1">
        <div className="text-[15px] font-semibold text-ink">{label}</div>
        <div className="text-[13px] leading-snug text-muted">
          {locked ? (
            <span className="inline-flex items-center gap-1">
              <Lock size={12} aria-hidden /> Locked while armed: disarm to change
            </span>
          ) : (
            hint
          )}
        </div>
      </div>
      <div className="shrink-0">{control}</div>
    </div>
  );
}

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

  const count = live.demoPositions ?? 0;

  return (
    <Section
      title="Demo trading"
      help="Real venue API with virtual money: signing, rejects and fills are real, the money is not."
      hint="Real venue API, virtual money. No arming needed, the risk limits still apply, and demo fills never reach the tax record."
      right={
        <span className="tabular text-[13px] text-muted">
          {count} demo position{count === 1 ? "" : "s"}
        </span>
      }
    >
      <List>
        {ROUTABLE.map(({ venue, label }) => {
          const on = ready.includes(venue);
          const demoName = cryptoDemoName(live);
          const where =
            venue === "crypto"
              ? live.demoExchange === "alpaca" && demoName
                ? "Alpaca paper account"
                : demoName
                  ? `${demoName} demo`
                  : "no demo exchange"
              : "Alpaca paper account";
          const apiOnly = venue === "crypto" && demoIsApiTestOnly(live);
          const notListed = venue === "crypto" && on ? (live.demoNotListed ?? []) : [];
          const maker = venue === "crypto" && on && live.demoExchange === "alpaca" ? alpacaMaker(live) : undefined;
          const makerStats = venue === "crypto" && on && live.demoExchange === "alpaca" ? alpacaMakerStats(live) : undefined;
          return (
            <div key={venue} className="py-3.5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[15px] font-semibold text-ink">{label}</div>
                  <div className="text-[13px] text-muted">{where}</div>
                </div>
                <Badge tone={on ? (apiOnly ? "warn" : "accent") : "neutral"}>{on ? (apiOnly ? "API test only" : "Demo ready") : "No demo keys"}</Badge>
              </div>
              {apiOnly && <p className="mt-1.5 text-[13px] text-warn">{demoApiTestNote(live)}</p>}
              {notListed.length > 0 && (
                <p className="mt-1.5 break-words text-[13px] text-muted">
                  Not listed on {demoName}, so demo skips them: {notListed.join(", ")}.
                </p>
              )}
              {maker && (
                <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2 text-[13px] text-muted">
                  <span title="Alpaca crypto: 0.15 % maker, 0.25 % taker. Stops and exits that must not wait still cross.">
                    Orders: {makerSummary(maker)}.
                  </span>
                  {liveMode() === "server" && (
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={busy !== ""}
                      onClick={() => {
                        const s = alpacaMaker(live)!;
                        void run("crypto:maker", async () => {
                          await setMakerRoute(ALPACA_CRYPTO_DEMO, { ...s, enabled: !s.enabled });
                          return s.enabled ? "Maker execution off: market orders" : "Maker execution on";
                        });
                      }}
                    >
                      {maker.enabled ? "Use market orders" : "Use maker limits"}
                    </Button>
                  )}
                </div>
              )}
              {makerStats && (
                <div
                  className="tabular mt-1 text-[13px] text-muted"
                  title="Maker orders on this route. Maker by qty: share of the filled amount that rested at our limit. Cost: realised slippage plus fee against what a market order was modelled to cost. Fallback: the rest went out as a marketable limit."
                >
                  <div>Maker {makerWindowLine(makerStats.d7)}</div>
                  <div>Maker {makerWindowLine(makerStats.d30)}</div>
                </div>
              )}
              {on && (
                <div className="mt-2.5 flex flex-wrap gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={PlugZap}
                    disabled={busy !== ""}
                    onClick={() => void run(`${venue}:check`, () => verifyVenue(venue, true, true))}
                  >
                    Check demo account
                  </Button>
                  <Button
                    variant="accent"
                    size="sm"
                    disabled={busy !== ""}
                    onClick={() => void run(`${venue}:test`, () => sendTestOrder(DEMO_TEST_MARKET[venue], 0, true))}
                  >
                    Demo connection test
                  </Button>
                </div>
              )}
              {[`${venue}:check`, `${venue}:test`, `${venue}:maker`].map((k) =>
                out[k] ? (
                  <div key={k} className="mt-2">
                    <Outcome ok={out[k].ok}>{out[k].text}</Outcome>
                  </div>
                ) : null
              )}
            </div>
          );
        })}
      </List>
      <More title="How demo trading works">
        <p className="text-[13px] leading-relaxed text-muted">
          A strategy set to Demo sends its orders to the venue's demo account with the demo keys from Settings (for
          crypto: Bybit, OKX or Binance demo keys, or the Alpaca paper account with PYTHIA_DEMO_EXCHANGE=alpaca):
          signing, size rules, rejects, latency and partial fills are all real, the money is not. No arming needed, the
          risk limits still apply, and demo fills never reach the tax record. See docs/DEMO.md for which venues trade on
          real prices.
        </p>
      </More>
    </Section>
  );
}

/**
 * The Alpaca paper account against the demo book, per Alpaca pair (several
 * markets can hold one pair there, so they are summed). Runs at startup and
 * every ten minutes on the backend; differences it can settle (an unposted
 * fee, the one holder off) are settled and listed, the rest is reported.
 */
function PaperReconcileCard() {
  const { live } = useStore();
  const d = live.demoReconcile;
  if (!d) return null;
  const rows = pairsToShow(d);
  const fees = d.estimatedFees ?? [];
  const paused = live.demoPaused ?? [];
  return (
    <Section
      title="Alpaca paper check"
      help="The Alpaca paper account compared with Pythia's demo book, pair by pair."
      hint={reconcileHeadline(d, Date.now())}
      right={
        <Badge tone={d.mismatches > 0 ? "warn" : d.checkedAt > 0 ? "good" : "neutral"}>
          {d.mismatches > 0 ? `${d.mismatches} to check` : d.checkedAt > 0 ? "In step" : "Not yet"}
        </Badge>
      }
    >
      {paused.map(([venue, until]) => (
        <Notice key={venue} tone="warning" className="mb-2">
          The {venue} demo route answered 403 and sends nothing until {new Date(until).toLocaleTimeString()}. Check the
          paper keys in Settings.
        </Notice>
      ))}
      {rows.length > 0 ? (
        <List>
          {rows.map((p) => (
            <div key={p.symbol} className="py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="break-all text-[15px] font-semibold text-ink">{p.symbol}</div>
                  <div className="tabular break-words text-[13px] text-muted">
                    Pythia {qty9(p.pythia)} · Alpaca {qty9(p.alpaca)}
                    {p.markets.length > 1 ? ` · ${p.markets.join(" + ")}` : ""}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="tabular text-[15px] font-semibold text-ink" title="Difference in dollars">
                    {signedMoney(p.diffUsd)}
                  </div>
                  <Badge tone={PAIR_STATUS[p.status].attention ? "warn" : "neutral"}>{PAIR_STATUS[p.status].label}</Badge>
                </div>
              </div>
              {p.note && <p className="mt-1 text-[13px] text-muted">{p.note}</p>}
            </div>
          ))}
        </List>
      ) : (
        <p className="text-[13px] text-muted">No pairs to show.</p>
      )}
      {d.strayOrders.length > 0 && (
        <Notice tone="warning" className="mt-2" title="Open at Alpaca, not followed by Pythia">
          <span className="break-words">{d.strayOrders.join("; ")}</span>
        </Notice>
      )}
      {fees.length > 0 && (
        <p className="mt-2 text-[13px] text-muted">
          {fees.length} fee{fees.length === 1 ? "" : "s"} booked as estimates ({money(estimatedFeeTotal(d))}): Alpaca
          posted no fee within 7 days, so the published tier 1 rate was booked in dollars. Not in the tax record.
        </p>
      )}
    </Section>
  );
}

/**
 * Adaptive execution: the learned table, and the switch.
 *
 * Execution is the only alpha here that does not require being right about the
 * market, so this shows the one number that matters: what each style actually
 * cost, measured against the price at the moment the decision was made.
 */
function ExecutionPolicyCard() {
  const { execution, adaptiveExecution, setAdaptiveExecution } = useStore();

  const STYLE_LABEL: Record<string, string> = {
    passive: "Rest inside the spread",
    join: "Sit at the touch",
    cross: "Take the offer",
  };

  return (
    <Section
      title="Adaptive execution"
      help="Lets orders rest inside the spread instead of always crossing it, and learns which way costs least."
      hint="What each way of placing an order actually cost, measured against the price when it was decided."
    >
      <SwitchRow
        label={adaptiveExecution ? "On: learning" : "Off: always cross"}
        on={adaptiveExecution}
        onChange={setAdaptiveExecution}
        hint={
          <>
            Crossing the spread on a signal that stays valid for hours is pure waste. With this on, orders may rest inside
            the spread instead, and the policy learns from what each choice actually cost, measured against the price at
            decision time, not the fill. An order that never fills is charged a penalty, because the signal was acted on
            late or not at all.
            {!adaptiveExecution && " While off, every order crosses, but costs are still recorded, so turning it on starts with real data."}
          </>
        }
      />

      {execution.length === 0 ? (
        <p className="border-t border-line pt-3 text-[13px] text-muted">Nothing measured yet. Rows appear once live orders have completed.</p>
      ) : (
        <>
          <List className="border-t border-line">
            {execution.map((r) => (
              <div key={`${r.context}-${r.style}`} className="flex items-start justify-between gap-3 py-3">
                <div className="min-w-0">
                  <div className="text-[15px] font-semibold text-ink">{STYLE_LABEL[r.style] ?? r.style}</div>
                  <div className="break-all text-[13px] text-muted">{r.context}</div>
                </div>
                <div className="shrink-0 text-right">
                  <div className={`tabular text-[15px] font-semibold ${r.meanCostBps < 0 ? "text-up" : "text-ink"}`}>{signedBps(r.meanCostBps)}</div>
                  <div className="tabular text-[13px] text-muted">
                    {r.fills} filled · <span className={r.misses > 0 ? "text-warn" : ""}>{r.misses} missed</span>
                  </div>
                </div>
              </div>
            ))}
          </List>
          <p className="mt-2 text-[13px] text-faint">
            Cost is measured against the price when the order was created; negative means it beat that price. Missed
            orders are charged a penalty, so a style that never fills does not look cheap.
          </p>
        </>
      )}
    </Section>
  );
}

/**
 * Why no order has reached the broker yet.
 *
 * Live routing is a chain of independent gates, every one of which fails
 * silently: keys, arm, a strategy set Live, an Alpaca-market universe, real
 * candles, an open session. Break any link and the symptom is identical (an
 * armed cockpit and an empty Alpaca dashboard), so the chain is laid out here
 * with the fix attached to whichever link is actually broken.
 */
function ReadinessCard() {
  const { live, strategies, barBacked, setStrategyState, passports } = useStore();
  const [fixErr, setFixErr] = useState("");

  // Only this strategy trades Alpaca markets today.
  const equityStrategies = strategies.filter((s) => s.venueClass === "alpaca");
  const liveEquity = equityStrategies.filter((s) => s.state === "live");
  const barsReady = equityStrategies.some((s) => s.universe.some((id) => barBacked.has(id)));
  // A strategy may only go live with a green Strategy Passport.
  const firstPassport = equityStrategies[0] ? passports.get(equityStrategies[0].id) : undefined;
  const canArmFirst = firstPassport?.liveReady ?? false;

  const steps: { label: string; ok: boolean; detail: string; fix?: { label: string; run: () => void } }[] = [
    {
      label: "Alpaca keys saved",
      ok: live.alpacaConnected,
      detail: live.alpacaConnected ? "in the OS keychain" : "Settings → Alpaca paper account",
    },
    {
      label: "Real equity candles loaded",
      ok: barsReady,
      detail: barsReady ? "indicators are running on real bars" : "waiting for Alpaca bars: strategies skip any market with under 30",
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
              // The engine can still refuse (a passport that went stale, an
              // autopilot that runs this strategy); show why, like the
              // Strategies page does, instead of dropping it.
              run: () =>
                void (async () => {
                  setFixErr("");
                  setFixErr(await changeStrategyState(setStrategyState, equityStrategies[0].id, "live"));
                })(),
            }
          : undefined,
    },
    {
      label: "Market session open",
      ok: !live.blockedReason,
      detail: live.blockedReason ?? (live.armed ? "clear to trade" : "checked once armed"),
    },
  ];

  const ready = readyCount(steps);

  return (
    <Section
      title="Why no orders yet?"
      help="Every gate an order passes on its way to the broker. All of them must be done."
      hint="Every link in the chain to the broker. A cross shows the one to fix."
      right={
        <Badge tone={ready.all ? "good" : "neutral"}>
          {ready.done}/{ready.total} ready
        </Badge>
      }
    >
      <List>
        {steps.map((s) => {
          const Icon = s.ok ? CheckCircle2 : XCircle;
          return (
            <div key={s.label} className="flex items-start gap-3 py-3">
              <Icon size={20} aria-hidden className={`mt-0.5 shrink-0 ${s.ok ? "text-up" : "text-muted"}`} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-[15px] font-semibold text-ink">{s.label}</span>
                  <Badge tone={s.ok ? "good" : "neutral"}>{s.ok ? "Done" : "Not yet"}</Badge>
                </div>
                <div className="mt-0.5 break-words text-[13px] leading-snug text-muted">{s.detail}</div>
                {s.fix && (
                  <div className="mt-2">
                    <Button variant="secondary" size="sm" onClick={s.fix.run}>
                      {s.fix.label}
                    </Button>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </List>
      {fixErr && (
        <Notice tone="danger" className="mt-2">
          {fixErr}
        </Notice>
      )}
      {ready.all && (
        <p className="mt-2 text-[13px] font-semibold text-up">Every gate is clear: the next signal on an Alpaca market routes to the broker.</p>
      )}
    </Section>
  );
}

/**
 * Per-market trace of the routing chain, straight from the engine.
 *
 * The readiness card above covers the global gates; this covers the per-market
 * ones the checklist can't see: no candles, already holding, already acted on
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

  async function test(marketId: string, symbol: string) {
    // A real order when real trading is armed: never on a single click.
    const ok = window.confirm(
      `Send one buy of ${symbol} at the venue's minimum size? If real trading is armed, this is a real order with real money.`,
    );
    if (!ok) return;
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
    <Section
      title="Per-market trace"
      help="For each Alpaca market, the first thing that would stop an order right now."
      hint={`${clear.length} of ${rows.length} markets are clear to route.`}
      right={
        <Button variant="secondary" size="sm" icon={RefreshCw} disabled={busy} onClick={() => void refresh()}>
          Refresh
        </Button>
      }
    >
      {err && (
        <Notice tone="danger" className="mb-2">
          {err}
        </Notice>
      )}
      {rows.length === 0 && !err ? (
        <p className="text-[13px] text-muted">No Alpaca markets in the engine yet.</p>
      ) : (
        <List>
          {rows.map((r) => (
            <div key={r.marketId} className="py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="break-all text-[15px] font-semibold text-ink">{r.symbol}</span>
                    <span className="tabular text-[13px] text-muted">{r.price.toFixed(2)}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    <Badge tone={r.barBacked ? "good" : "neutral"}>{r.bars} bars</Badge>
                    {r.quoteAgeSec > 30 && <Badge tone="bad">Quote {r.quoteAgeSec}s old</Badge>}
                    {r.hasPosition && <Badge tone="accent">Holding</Badge>}
                  </div>
                </div>
                <Button variant="secondary" size="sm" onClick={() => void test(r.marketId, r.symbol)}>
                  Connection test
                </Button>
              </div>
              {r.signal && <p className="mt-1.5 break-words text-[13px] text-ink">Signal: {r.signal}</p>}
              <div className="mt-1.5">
                <Outcome ok={!r.suppressed} okWord="Clear" failWord="Held" soft>
                  {r.suppressed ?? "the next signal routes to the broker"}
                </Outcome>
              </div>
            </div>
          ))}
        </List>
      )}
      {testMsg && (
        <p role="status" className="mt-2 break-words text-[13px] text-muted">
          {testMsg}
        </p>
      )}
      <p className="mt-2 text-[13px] leading-relaxed text-faint">
        <b>Connection test</b> sends one buy at the venue's minimum size through the full path (risk manager, broker,
        fill), so a wrong key or a closed session surfaces immediately. It is a connection test, not a strategy: it
        needs no Strategy Passport, it is the only order that skips one, and no strategy is set live by it.
      </p>
    </Section>
  );
}
