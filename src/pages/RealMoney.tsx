// Everything with real money in one place: the pump.fun bot (the summary and
// the live chart of its own page), every live autopilot with its trades, the
// engine journal's live Kraken and Alpaca fills, and one P&L line in euro over
// all of it. Read only, except what the reused autopilot cards already offer
// (pause, stop, edit with the typed phrase). The pump.fun page keeps its
// limits, kill switch and every trade. The on-chain wallet (the locked Solana
// trader, docs/ONCHAIN-STAGE2.md) has its section here: address, balances,
// conversions with a confirm, trades and its own kill switch.

import { useMemo, useRef, useState } from "react";
import { Banknote, ChevronRight, ScrollText } from "lucide-react";
import { AreaChart, Badge, BigNumber, Card, Empty, List, ListRow, Notice, Page, SectionTitle, money } from "../design";
import { LoadingRows, Nothing, Row, Section, plural } from "../pagekit";
import { isActive, groupByMoney, realMoneyRows } from "../autopilot";
import { cardModel } from "../flows/autopilotView";
import { fillRows, practiceAutopilots } from "../practice";
import { useStore } from "../store";
import { openPage } from "../navigate";
import { usePageVisible } from "../pageVisible";
import { sol, tone } from "../pumpfunLive";
import { autopilotLine, combineLines, euro, liveFills, pumpfunLine, realMoneyTotal } from "../realMoney";
import { AutopilotCard, RealMoneySummary, useNow } from "./Autopilots";
import { useAutopilotApi } from "./Autopilot";
import { PumpfunLiveChart, PumpfunSummary, SocketBadge, usePumpfunLive } from "./PumpfunWallet";
import { OnchainWallet } from "./OnchainWallet";
import type { AutopilotStatus } from "../types";

const when = (ms: number) => new Date(ms).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/** The trades of one live autopilot, newest first, from the engine's orders. */
function AutopilotTrades({ s }: { s: AutopilotStatus }) {
  const { orders, markets } = useStore();
  const rows = useMemo(() => fillRows(orders.filter((o) => o.route === "live"), markets, [s], 20), [orders, markets, s]);
  return (
    <Card title={`Trades of ${s.config.name}`} label={`Trades of ${s.config.name}`}>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">No real-money fill yet.</p>
      ) : (
        <List>
          {rows.map((f) => (
            <ListRow
              key={f.id}
              ticker={f.coin}
              title={`${f.side === "buy" ? "Bought" : "Sold"} ${f.coin}`}
              subtitle={`${when(f.ts)} · ${f.qty} at ${money(f.price)}${f.fee != null ? ` · fee ${money(f.fee)}` : f.feeNote ? ` · fee ${f.feeNote}` : ""}`}
              right={money(f.qty * f.price)}
            />
          ))}
        </List>
      )}
    </Card>
  );
}

export function RealMoney() {
  const ref = useRef<HTMLDivElement>(null);
  // The socket and the polling only run while this page is in front; the pump.fun page has its own.
  const shownNow = usePageVisible(ref);
  const pf = usePumpfunLive(shownNow);
  const api = useAutopilotApi();
  const { positions, strategies, limits, live, journal } = useStore();
  const now = useNow();
  const [at, setAt] = useState<number | null>(null);

  const names = useMemo(() => Object.fromEntries(strategies.map((s) => [s.id, s.name])), [strategies]);
  const real = groupByMoney(practiceAutopilots(api.autopilots, now)).real;
  const running = real.filter(isActive);
  const stopped = real.filter((s) => !isActive(s));
  const rows = realMoneyRows(running, live);
  const btc = api.btc ? { times: api.btc.times, closes: api.btc.closes } : null;
  const fills = liveFills(journal);

  const v = pf.v;
  const rate = v?.solEur ?? null;
  const eurUsd = v?.eurUsd ?? null;
  const pfTotal = v?.status ? v.status.pnlTotalSol : null;
  const total = realMoneyTotal(pfTotal, rate, real, eurUsd);
  const line = useMemo(
    () => combineLines([pumpfunLine(v?.trades ?? [], pfTotal, rate), ...real.map((s) => autopilotLine(s, eurUsd))]),
    [v, pfTotal, rate, real, eurUsd],
  );
  const shown = at == null ? total.eur : line[at]?.[1] ?? total.eur;

  const card = (s: AutopilotStatus) => (
    <div key={s.config.id} className="space-y-2">
      <AutopilotCard s={s} model={cardModel(s, positions, now, btc, names)} api={api} />
      <AutopilotTrades s={s} />
    </div>
  );

  return (
    <div ref={ref}>
      <Page
        title="Real money"
        subtitle="Everything that trades real money, in one place: the pump.fun bot, every live autopilot and the live fills at Kraken and Alpaca. Practice money stays on the Autopilot page."
        right={<SocketBadge socket={pf.socket} onRefresh={() => void pf.load()} />}
      >
        {limits.killSwitch && (
          <Notice tone="danger" title="Kill switch is on">
            The engine buys nothing new until you switch it off. The pump.fun bot has its own kill switch on its page.
          </Notice>
        )}

        <Card label="All real money together">
          <BigNumber
            label={at == null ? "Profit or loss in euro, all real money" : `After ${when(line[at][0])}`}
            value={euro(shown, true)}
            sub={total.missing.length > 0 ? <span className="text-[13px] text-muted">Without {total.missing.join(" and ")}.</span> : undefined}
          />
          <div className="mt-3">
            <AreaChart
              data={line.map((p) => p[1])}
              height={150}
              baseline={0}
              label={`Real-money profit or loss in euro over time, now ${euro(total.eur, true)}`}
              onScrub={(x) => setAt(x ? x.index : null)}
              empty="The line starts with the first real-money trade."
            />
          </div>
          <div className="mt-3 divide-y divide-line">
            <Row
              label="pump.fun bot"
              value={total.pumpfunEur == null ? (pfTotal == null ? "n/a" : sol(pfTotal, true)) : euro(total.pumpfunEur, true)}
              valueSub={pfTotal == null ? undefined : sol(pfTotal, true)}
              tone={tone(pfTotal)}
              help="Since its first live trade, fees included; euro at today's SOL price."
            />
            <Row
              label={`Live autopilots (${real.length})`}
              value={total.autopilotsEur == null ? money(total.autopilotsUsd) : euro(total.autopilotsEur, true)}
              valueSub={real.length ? `${total.autopilotsUsd >= 0 ? "+" : ""}${money(total.autopilotsUsd)}` : undefined}
              tone={tone(total.autopilotsUsd)}
              help="Running and stopped this week, in US dollars as the engine counts them; euro at Kraken's EUR/USD."
            />
          </div>
          {eurUsd && <p className="mt-2 text-[12px] text-faint">1 EUR = {eurUsd.price.toFixed(4)} USD{rate ? ` · 1 SOL = ${euro(rate.price)}` : ""}</p>}
        </Card>

        <SectionTitle
          right={
            <button type="button" onClick={() => openPage("pumpfun")} className="inline-flex items-center gap-1 text-[13px] font-semibold text-accent hover:underline">
              Limits, stop, every trade <ChevronRight size={14} aria-hidden />
            </button>
          }
        >
          pump.fun bot
        </SectionTitle>
        {pf.err && !v && <Notice tone="warning" title="Could not read the pump.fun live service">{pf.err}</Notice>}
        {!v && !pf.err && <LoadingRows rows={3} label="Reading the live service" />}
        {v && (
          <>
            <PumpfunSummary v={v} />
            <PumpfunLiveChart coins={pf.coins} now={pf.now} rate={rate} socket={pf.socket} />
          </>
        )}

        <SectionTitle>On-chain wallet</SectionTitle>
        <OnchainWallet active={shownNow} />

        <SectionTitle>Live autopilots</SectionTitle>
        {api.loading ? (
          <Card>
            <LoadingRows rows={2} label="Waiting for the engine to report its autopilots" />
          </Card>
        ) : running.length === 0 ? (
          <Card>
            <Empty icon={Banknote} title="No real-money autopilot running">
              A real-money autopilot is started under Autopilot, Full setup and analysis (advanced view), with your own keys and a typed confirmation.
            </Empty>
          </Card>
        ) : (
          <>
            <RealMoneySummary rows={rows} />
            {running.map(card)}
          </>
        )}
        {stopped.length > 0 && (
          <section aria-label="Real money stopped this week" className="space-y-3">
            <h3 className="px-1 text-[13px] font-semibold text-muted">Stopped this week</h3>
            {stopped.map(card)}
          </section>
        )}

        <Section title="Live fills" hint="Real-money fills at Kraken and Alpaca from the engine's journal, newest first. Demo and practice fills are left out.">
          {fills.length === 0 ? (
            <Nothing icon={ScrollText} title="No live fill in the journal" />
          ) : (
            <ul className="divide-y divide-line">
              {fills.map((e) => (
                <li key={e.id} className="py-3">
                  <div className="flex items-center gap-1.5">
                    <Badge tone="bad">Live</Badge>
                    <span className="tabular ml-auto text-[13px] text-faint">{when(e.ts)}</span>
                  </div>
                  <p className="mt-1 break-words text-[15px] text-ink">{e.message}</p>
                </li>
              ))}
            </ul>
          )}
          {fills.length > 0 && <p className="mt-2 text-[13px] text-muted">{plural(fills.length, "fill")} shown.</p>}
        </Section>

      </Page>
    </div>
  );
}
