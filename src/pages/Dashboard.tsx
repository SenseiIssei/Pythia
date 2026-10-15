import { Activity, Wallet } from "lucide-react";
import { useStore } from "../store";
import {
  Chip,
  Delta,
  KeyStats,
  LineChart,
  Nothing,
  PageShell,
  Row,
  Rows,
  Section,
  clock,
  plural,
  toneOf,
  usd,
  usdShort,
} from "../pagekit";
import { kindInfo } from "../pagekit/journal";

const venueLabel: Record<string, string> = {
  polymarket: "Polymarket",
  crypto: "Crypto",
  alpaca: "Alpaca (US shares)",
};

/** The live cockpit: account value, today's result, the curve, venues and the latest engine events. */
export function Dashboard() {
  const { portfolio, journal, positions } = useStore();
  const dayPnl = portfolio.realizedPnl + portfolio.unrealizedPnl;
  const dayPnlPct = portfolio.dayStartEquity > 0 ? (dayPnl / portfolio.dayStartEquity) * 100 : 0;
  const feed = journal.slice(0, 12);
  const live = portfolio.mode === "live";
  const tone = toneOf(dayPnl);

  return (
    <PageShell
      title="Dashboard"
      subtitle={live ? "The live cockpit. Real orders may be placed." : "The live cockpit on the paper engine, with simulated money."}
      right={<Chip tone={live ? "bad" : "neutral"}>{live ? "Live" : "Simulated"}</Chip>}
    >
      <KeyStats
        items={[
          { label: "Equity", value: usd(portfolio.equity), sub: <Delta usd={dayPnl} pct={dayPnlPct} tone={tone} />, help: "What the whole account is worth right now." },
          { label: "Open Exposure", value: usdShort(portfolio.grossExposure), sub: plural(positions.length, "position") },
          { label: "Unrealized", value: usd(portfolio.unrealizedPnl), tone: toneOf(portfolio.unrealizedPnl), sub: "on open positions" },
        ]}
      />

      <Section title="Equity Curve" hint="The account's value over this session.">
        <LineChart series={[{ label: "Equity", data: portfolio.equityCurve }]} tone={tone} height={170} label="Equity over this session" format={usdShort} />
        <div className="fl-muted fl-num mt-2 flex justify-between text-sm">
          <span>Start {usd(portfolio.dayStartEquity, 0)}</span>
          <span>Now {usd(portfolio.equity, 0)}</span>
        </div>
      </Section>

      <Section title="Venue Balances" hint="Where the money sits. Connected venues have keys set; the rest are simulated.">
        {portfolio.balances.length === 0 ? (
          <Nothing icon={Wallet} title="No venues yet" />
        ) : (
          <Rows>
            {portfolio.balances.map((b) => (
              <Row
                key={b.venue}
                label={venueLabel[b.venue] ?? b.venue}
                sub={b.connected ? "Connected: real data or orders can reach it" : "Simulated: no keys set"}
                value={usd(b.equity, 0)}
              />
            ))}
          </Rows>
        )}
      </Section>

      <Section title="Live Activity" hint="The engine's latest events, newest first. The Journal keeps all of them.">
        {feed.length === 0 ? (
          <Nothing icon={Activity} title="Waiting for the first engine events" />
        ) : (
          <Rows>
            {feed.map((e) => {
              const k = kindInfo(e.kind);
              return (
                <div key={e.id} className="py-3">
                  <div className="flex items-center justify-between gap-2">
                    <Chip tone={k.tone} title={k.help}>
                      {k.label}
                    </Chip>
                    <span className="fl-muted fl-num text-sm">{clock(e.ts)}</span>
                  </div>
                  <p className="mt-1 break-words text-[15px]">{e.message}</p>
                </div>
              );
            })}
          </Rows>
        )}
      </Section>
    </PageShell>
  );
}
