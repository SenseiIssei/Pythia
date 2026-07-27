import { useState } from "react";
import {
  ShieldCheck,
  TriangleAlert,
  Power,
  ChevronDown,
  Eye,
  Activity,
  Wallet,
  HelpCircle,
} from "lucide-react";
import { Card, Sparkline, Button, fmtUsd } from "../components/ui";
import { useStore } from "../store";
import { setUiMode } from "../uiMode";

/**
 * The default view, written for someone who has never traded.
 *
 * It answers four questions in this order, because that is the order they
 * actually matter in: is my real money at risk, how am I doing, what is it
 * doing, and what does it think. Every number is in plain words or currency —
 * no basis points, no P&L, no drawdown, no Sharpe. Anything a beginner cannot
 * act on is not here.
 */
export function Home() {
  const { portfolio, positions, journal, strategies, markets, forecasts, forecastStats, live, limits, toggleKill } =
    useStore();

  const realMoney = live.armed && !live.paper && !live.dryRun;
  const anythingLive = live.armed;
  const change = portfolio.equity - portfolio.dayStartEquity;
  const changePct = portfolio.dayStartEquity > 0 ? (change / portfolio.dayStartEquity) * 100 : 0;
  const running = strategies.filter((s) => s.state !== "paused").length;
  const tradesToday = journal.filter((j) => j.kind === "fill").length;
  const realPositions = positions.filter((p) => p.live).length;

  return (
    <div className="animate-fade-in mx-auto max-w-3xl">
      {/* 1 · Is my money at risk? Nothing outranks this. */}
      <MoneyBanner realMoney={realMoney} anythingLive={anythingLive} realPositions={realPositions} />

      {/* 2 · How am I doing? */}
      <Card className="mb-4">
        <div className="mb-1 text-sm text-cyber-text-dim">
          {realMoney ? "Your account is worth" : "Your practice balance is"}
        </div>
        <div className="mb-1 text-4xl font-bold text-glow">{fmtUsd(portfolio.equity, 2)}</div>
        <div className={`mb-4 text-sm ${change >= 0 ? "text-success" : "text-danger"}`}>
          {change >= 0 ? "Up" : "Down"} {fmtUsd(Math.abs(change), 2)} today ({changePct >= 0 ? "+" : ""}
          {changePct.toFixed(2)}%)
          <span className="ml-2 text-cyber-text-faint">
            · started the day at {fmtUsd(portfolio.dayStartEquity, 2)}
          </span>
        </div>
        <Sparkline data={portfolio.equityCurve} height={120} tone={change >= 0 ? "green" : "red"} />
      </Card>

      {/* 3 · What is it doing? */}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <PlainStat label="Markets watched" value={String(markets.length)} icon={Eye} />
        <PlainStat label="Strategies running" value={String(running)} icon={Activity} />
        <PlainStat label="Trades made today" value={String(tradesToday)} icon={Wallet} />
        <PlainStat
          label="Things it owns"
          value={String(positions.length)}
          icon={Wallet}
          hint={realPositions > 0 ? `${realPositions} bought for real` : undefined}
        />
      </div>

      {/* 4 · What does it think? */}
      <TopPredictions forecasts={forecasts} untrusted={forecastStats.trustedSources === 0} />

      {/* The stop button, always reachable, always explained. */}
      <Card className={`mb-4 ${limits.killSwitch ? "border-danger/50 bg-danger/10" : ""}`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="text-sm text-cyber-text-dim">
            <div className="font-bold text-cyber-text">
              {limits.killSwitch ? "Stopped — it is not opening anything new" : "Emergency stop"}
            </div>
            {limits.killSwitch
              ? "It can still close what it already owns. Press again to let it start buying."
              : "Stops it opening anything new, immediately. It can still close what it already owns."}
          </div>
          <Button tone={limits.killSwitch ? "cyan" : "red"} icon={Power} onClick={toggleKill}>
            {limits.killSwitch ? "Let it trade again" : "Stop everything"}
          </Button>
        </div>
      </Card>

      <Explainer />
    </div>
  );
}

function MoneyBanner({
  realMoney,
  anythingLive,
  realPositions,
}: {
  realMoney: boolean;
  anythingLive: boolean;
  realPositions: number;
}) {
  if (realMoney) {
    return (
      <div className="mb-4 flex items-start gap-3 rounded-lg border border-danger/50 bg-danger/15 px-4 py-3 animate-pulse-red">
        <TriangleAlert size={20} className="mt-0.5 shrink-0 text-danger" />
        <div className="text-sm text-cyber-text-dim">
          <div className="text-base font-bold text-danger text-glow-red">This is real money</div>
          Orders are going to a real broker and can lose real money. You can stop it at any time with
          the button below.
        </div>
      </div>
    );
  }
  return (
    <div className="mb-4 flex items-start gap-3 rounded-lg border border-success/40 bg-success/10 px-4 py-3">
      <ShieldCheck size={20} className="mt-0.5 shrink-0 text-success" />
      <div className="text-sm text-cyber-text-dim">
        <div className="text-base font-bold text-success">Practice mode — no real money</div>
        Everything here is simulated. Nothing leaves this computer and nothing can be lost.
        {anythingLive && " (A test connection to a broker is armed, but on its practice account.)"}
        {realPositions > 0 && (
          <div className="mt-1 font-bold text-warning">
            Careful: {realPositions} position{realPositions > 1 ? "s were" : " was"} bought for real
            earlier and {realPositions > 1 ? "are" : "is"} still open at the broker.
          </div>
        )}
      </div>
    </div>
  );
}

function PlainStat({
  label,
  value,
  icon: Icon,
  hint,
}: {
  label: string;
  value: string;
  icon: typeof Eye;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-cyber-border bg-cyber-surface/40 px-3 py-2.5">
      <div className="mb-1 flex items-center gap-1.5 text-[11px] text-cyber-text-faint">
        <Icon size={11} /> {label}
      </div>
      <div className="text-xl font-bold">{value}</div>
      {hint && <div className="mt-0.5 text-[10px] text-warning">{hint}</div>}
    </div>
  );
}

/**
 * The three markets it currently has the strongest view on, in words.
 *
 * A beginner does not need the pooled log-odds; they need to know whether the
 * app disagrees with the market, by how much, and whether it has any business
 * disagreeing yet.
 */
function TopPredictions({
  forecasts,
  untrusted,
}: {
  forecasts: ReturnType<typeof useStore>["forecasts"];
  untrusted: boolean;
}) {
  const top = [...forecasts]
    .filter((f) => f.kind === "outcome")
    .sort((a, b) => Math.abs(b.edge) - Math.abs(a.edge))
    .slice(0, 3);

  return (
    <Card title="What it thinks" className="mb-4">
      {untrusted && (
        <div className="mb-3 rounded border border-warning/30 bg-warning/5 px-3 py-2 text-sm text-cyber-text-dim">
          <b className="text-warning">It is still learning.</b> Every prediction it makes is written
          down and checked against what actually happened. Until its guesses beat the market's own
          price, it does not act on them — so right now it mostly agrees with the market on purpose.
        </div>
      )}
      {top.length === 0 ? (
        <div className="text-sm text-cyber-text-faint">
          No prediction markets loaded yet. They arrive within a few seconds of starting.
        </div>
      ) : (
        <div className="space-y-2">
          {top.map((f) => {
            const mine = Math.round(f.ensembleP * 100);
            const mkt = Math.round(f.marketP * 100);
            const diff = mine - mkt;
            return (
              <div key={f.marketId} className="rounded border border-cyber-border bg-cyber-surface/40 px-3 py-2">
                <div className="mb-1 text-sm">{f.symbol}</div>
                <div className="text-sm text-cyber-text-dim">
                  Everyone else says <b className="text-cyber-text">{mkt}%</b> likely. Pythia says{" "}
                  <b className="text-accent">{mine}%</b>.{" "}
                  {Math.abs(diff) < 1 ? (
                    <span className="text-cyber-text-faint">It agrees.</span>
                  ) : (
                    <span className="text-cyber-text-faint">
                      It thinks that is {Math.abs(diff)} point{Math.abs(diff) === 1 ? "" : "s"} too{" "}
                      {diff > 0 ? "low" : "high"}.
                    </span>
                  )}
                </div>
                {f.action === "hold" && (
                  <div className="mt-1 text-[11px] text-cyber-text-faint">
                    Not acting on it — {plainReason(f.reason)}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

/** Translate the engine's reason string out of trading vocabulary. */
function plainReason(reason: string): string {
  if (reason.includes("track record")) {
    return "it has not proven itself yet.";
  }
  if (reason.includes("round-trip cost")) {
    return "the fees would eat the whole difference.";
  }
  if (reason.includes("below the")) {
    return "the difference is too small to be worth the fees.";
  }
  if (reason.includes("no forecaster")) {
    return "nothing has an opinion on this one.";
  }
  return reason;
}

function Explainer() {
  const [open, setOpen] = useState(false);
  return (
    <Card>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 text-left text-sm font-medium text-accent"
      >
        <HelpCircle size={15} />
        What is this app actually doing?
        <ChevronDown size={14} className={`ml-auto transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="mt-3 space-y-3 text-sm leading-relaxed text-cyber-text-dim">
          <p>
            Pythia watches a set of markets — some prediction markets (&ldquo;will this happen?&rdquo;),
            some crypto, some shares — and forms an opinion about where each is going. When it thinks
            the market is wrong by enough to be worth the fees, it can place a trade.
          </p>
          <p>
            <b className="text-cyber-text">It starts in practice mode.</b> The balance is fake, the
            trades are simulated, and nothing can be lost. Turning on real trading takes several
            deliberate steps and a typed confirmation — it cannot happen by accident.
          </p>
          <p>
            <b className="text-cyber-text">It has to earn your trust, literally.</b> Every prediction
            is written down and later checked against what really happened. Until a source of
            predictions beats the market's own price over a real track record, Pythia refuses to act
            on it. That is why a fresh install mostly agrees with the market and trades very little.
          </p>
          <p>
            <b className="text-cyber-text">Nobody can promise you profit.</b> Not this app, not
            anyone. Most automated trading loses money to fees. Only ever use money you can afford to
            lose entirely.
          </p>
          <p className="text-cyber-text-faint">
            Want the full instrument panel — charts, strategies, backtests, risk limits?{" "}
            <button
              onClick={() => setUiMode("advanced")}
              className="font-medium text-accent underline underline-offset-2 hover:text-glow-cyan"
            >
              Switch on advanced view
            </button>
            . You can switch back any time in Settings.
          </p>
        </div>
      )}
    </Card>
  );
}
