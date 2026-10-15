import { Activity, Wallet } from "lucide-react";
import { useStore } from "../store";
import { AreaChart, Badge, Change, Chip, List, Page, changeTone, compactMoney, money } from "../design";
import { KeyStats, Nothing, Row, Section, clock, plural } from "../pagekit";
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
  const tone = changeTone(dayPnl);

  return (
    <Page
      title="Dashboard"
      subtitle={live ? "The live cockpit. Real orders may be placed." : "The live cockpit on the paper engine, with simulated money."}
      right={<Badge tone={live ? "bad" : "neutral"}>{live ? "Live" : "Simulated"}</Badge>}
    >
      <KeyStats
        items={[
          {
            label: "Equity",
            value: money(portfolio.equity),
            sub: <Change usd={dayPnl} pct={dayPnlPct} tone={tone} size="sm" suffix="today" />,
            help: "What the whole account is worth right now.",
          },
          { label: "Open Exposure", value: compactMoney(portfolio.grossExposure), sub: plural(positions.length, "position") },
          { label: "Unrealized", value: money(portfolio.unrealizedPnl), tone: changeTone(portfolio.unrealizedPnl), sub: "on open positions" },
        ]}
      />

      <Section title="Equity Curve" hint="The account's value over this session.">
        <AreaChart data={portfolio.equityCurve} tone={tone} height={170} label="Equity over this session" baseline={portfolio.dayStartEquity} />
        <div className="tabular mt-2 flex justify-between text-[13px] text-muted">
          <span>Start {money(portfolio.dayStartEquity, 0)}</span>
          <span>Now {money(portfolio.equity, 0)}</span>
        </div>
      </Section>

      <Section title="Venue Balances" hint="Where the money sits. Connected venues have keys set; the rest are simulated.">
        {portfolio.balances.length === 0 ? (
          <Nothing icon={Wallet} title="No venues yet" />
        ) : (
          <List>
            {portfolio.balances.map((b) => (
              <Row
                key={b.venue}
                label={venueLabel[b.venue] ?? b.venue}
                sub={b.connected ? "Connected: real data or orders can reach it" : "Simulated: no keys set"}
                value={money(b.equity, 0)}
              />
            ))}
          </List>
        )}
      </Section>

      <Section title="Live Activity" hint="The engine's latest events, newest first. The Journal keeps all of them.">
        {feed.length === 0 ? (
          <Nothing icon={Activity} title="Waiting for the first engine events" />
        ) : (
          <List>
            {feed.map((e) => {
              const k = kindInfo(e.kind);
              return (
                <div key={e.id} className="py-3">
                  <div className="flex items-center justify-between gap-2">
                    <Chip tone={k.tone} title={k.help}>
                      {k.label}
                    </Chip>
                    <span className="tabular text-[13px] text-faint">{clock(e.ts)}</span>
                  </div>
                  <p className="mt-1 break-words text-[15px] text-ink">{e.message}</p>
                </div>
              );
            })}
          </List>
        )}
      </Section>
    </Page>
  );
}
