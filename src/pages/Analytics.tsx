import { useMemo } from "react";
import { Gauge, LineChart as LineChartIcon, ReceiptText, Trophy } from "lucide-react";
import { useStore } from "../store";
import { AreaChart, Badge, LineChart, List, Page, changeTone, money, signedPct, type ChipTone } from "../design";
import { KeyStats, More, Nothing, Row, Section, Term, num, pct, plural, share } from "../pagekit";
import { curveReturn, drawdownSeries, sumPnl, worstDip } from "../pagekit/insight";
import { costWarning } from "../components/PnlBreakdown";
import { breakdown } from "../engine/costs";
import type { FillRoute, PnlBreakdown, SlippageRow, StrategyConfig } from "../types";
import { makerShare } from "../lib/maker";

const STATE_TONE: Record<string, ChipTone> = { live: "bad", paused: "neutral", demo: "accent" };

export function Analytics() {
  const { portfolio, strategies, orders, slippage } = useStore();

  // drawdown series (% below running peak) from the equity curve
  const drawdown = useMemo(() => drawdownSeries(portfolio.equityCurve), [portfolio.equityCurve]);
  const curMaxDD = useMemo(() => worstDip(portfolio.equityCurve), [portfolio.equityCurve]);
  const sessionRet = useMemo(() => curveReturn(portfolio.equityCurve), [portfolio.equityCurve]);

  const ranked = useMemo(() => [...strategies].filter((s) => s.id !== "manual").sort((a, b) => b.pnl - a.pnl), [strategies]);
  const book = useMemo(() => sumPnl(ranked.map(pnlOf)), [ranked]);
  const active = ranked.filter((s) => s.equityCurve.length > 1 && (s.pnl !== 0 || s.trades > 0));

  const fills = orders.filter((o) => o.status === "filled").slice(0, 30);

  return (
    <Page title="Analytics" subtitle="How deep the dips were, which strategies earned their keep after costs, and every fill.">
      <KeyStats
        items={[
          {
            label: "What you kept",
            value: money(book.net),
            tone: changeTone(book.net),
            sub: `${money(book.gross)} before costs, ${money(book.costs)} in costs, across ${plural(ranked.length, "strategy", "strategies")}`,
            help: "Net: what all strategies made together after fees and slippage.",
          },
          {
            label: "This session",
            value: signedPct(sessionRet),
            tone: sessionRet == null ? "plain" : changeTone(sessionRet),
            sub: "change in account value",
            help: "How much the whole account moved from the start of this session to now.",
          },
          {
            label: "Worst dip",
            value: pct(curMaxDD, 2),
            tone: curMaxDD < -0.005 ? "warn" : "plain",
            sub: "deepest fall below a high",
          },
        ]}
      />

      <Section title="Portfolio Drawdown" hint="How far below its best point the account was, over this session. Zero is at the high.">
        <AreaChart
          data={drawdown.length > 1 ? drawdown : [0, 0]}
          height={120}
          tone={curMaxDD < -0.005 ? "down" : "flat"}
          label="Drawdown over the session"
          renderTip={(i) => pct(drawdown[i] ?? 0, 2)}
        />
      </Section>

      <Section title="Strategy Equity Curves" hint="Each strategy's result over time, on one scale.">
        {active.length === 0 ? (
          <Nothing icon={LineChartIcon} title="No curves yet">
            Each strategy's curve appears once it has closed a trade.
          </Nothing>
        ) : (
          <LineChart height={180} label="Equity of each strategy" series={active.map((s) => ({ label: s.name.split(" · ")[0], data: s.equityCurve }))} />
        )}
      </Section>

      <Section
        title="Strategy Leaderboard"
        hint="Best first. The big number is what it kept after costs; a warning means costs ate more than 40% of its gross."
      >
        {ranked.length === 0 ? (
          <Nothing icon={Trophy} title="No strategies yet">
            Add one on the Strategies page and its results show here.
          </Nothing>
        ) : (
          <List>
            {ranked.map((s) => (
              <StrategyRow key={s.id} s={s} />
            ))}
          </List>
        )}
        {ranked.length > 0 && ranked.every((s) => s.trades === 0) && (
          <p className="mt-2 text-[13px] text-muted">No closed trades yet. The numbers fill in as positions close.</p>
        )}
        <More title="How these numbers are counted">
          <p className="text-[13px] leading-relaxed text-muted">
            <Term>Gross</Term> is the closed trades at the quoted price; <Term>Costs</Term> are their slippage plus every fee paid
            (an open position's entry fee shows before its P&amp;L does); <Term>Net</Term> is what was kept. A warning marks a
            strategy whose costs exceed 40% of its gross.
          </p>
        </More>
      </Section>

      <SlippageSection rows={slippage} />

      <Section title="Trade Log" hint="The last 30 fills, newest first.">
        {fills.length === 0 ? (
          <Nothing icon={ReceiptText} title="No fills yet">
            Fills show up here as strategies trade.
          </Nothing>
        ) : (
          <List>
            {fills.map((o) => {
              const maker = makerShare(o);
              return (
                <div key={o.id} className="py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-[15px] font-semibold text-ink">
                        <span className={o.side === "buy" ? "text-up" : "text-down"}>{o.side === "buy" ? "Buy" : "Sell"}</span>{" "}
                        <span className="break-all">{o.marketId}</span>
                      </div>
                      <div className="tabular text-[13px] text-muted">
                        {new Date(o.ts).toLocaleTimeString()} · {num(o.filledQty, 4)} at {o.avgFillPrice?.toLocaleString() ?? "n/a"}
                      </div>
                    </div>
                    <div className="flex shrink-0 flex-wrap justify-end gap-1">
                      {o.route && o.route !== "paper" && (
                        <Badge tone={o.route === "live" ? "bad" : "accent"} title={ROUTE_HELP[o.route]}>
                          {o.route === "live" ? "Live" : "Demo"}
                        </Badge>
                      )}
                      {maker && (
                        <Badge title="Filled resting at our own limit (maker fee) vs by crossing (taker fee)">{maker}</Badge>
                      )}
                      <Badge>{o.strategyId}</Badge>
                    </div>
                  </div>
                  {(o.realisedSlippageBps !== undefined || o.realisedCostBps !== undefined) && (
                    <div className="tabular mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[13px]">
                      {o.realisedSlippageBps !== undefined && (
                        <span
                          className={o.realisedSlippageBps > (o.modelledSlippageBps ?? 0) * 1.5 ? "text-warn" : "text-muted"}
                          title="Realised slippage against the arrival price, next to what the cost model expected"
                        >
                          Slippage {num(o.realisedSlippageBps, 1)} bps vs {num(o.modelledSlippageBps ?? 0, 1)} modelled
                        </span>
                      )}
                      {o.realisedCostBps !== undefined && (
                        <span
                          className={o.realisedCostBps > (o.modelledCostBps ?? 0) ? "text-warn" : "text-muted"}
                          title="Slippage plus the fee of the maker and taker mix, next to the model's cost for a market order"
                        >
                          Cost {num(o.realisedCostBps, 1)} bps vs {num(o.modelledCostBps ?? 0, 1)} as taker
                        </span>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </List>
        )}
      </Section>
    </Page>
  );
}

/** One strategy: name and state on the left, what it kept on the right, the rest in the line under it. */
function StrategyRow({ s }: { s: StrategyConfig }) {
  const p = pnlOf(s);
  const warn = costWarning(p);
  return (
    <div className="py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="min-w-0 break-words text-[15px] font-semibold text-ink">{s.name}</span>
            <Badge tone={STATE_TONE[s.state] ?? "neutral"}>{s.state}</Badge>
          </div>
          <div className="tabular mt-0.5 text-[13px] text-muted">
            {plural(s.trades, "trade")} · <Term k="Win">{share(s.winRate)} won</Term> · <Term k="PF">PF {num(s.profitFactor)}</Term> ·{" "}
            <Term k="maxDD">worst dip {money(s.maxDrawdown)}</Term>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className={`tabular text-[15px] font-semibold ${p.net > 0 ? "text-up" : p.net < 0 ? "text-down" : "text-ink"}`}>{money(p.net)}</div>
          <div className="tabular text-[13px] text-muted">
            {money(p.gross)} gross
          </div>
          <div className={`tabular text-[13px] ${warn ? "text-warn" : "text-muted"}`}>{p.costs > 0 ? `−${money(p.costs)}` : money(0)} costs</div>
        </div>
      </div>
      {warn && <p className="mt-1 text-[13px] text-warn">{warn}</p>}
    </div>
  );
}

const ROUTE_HELP: Record<FillRoute, string> = {
  paper: "Simulated by Pythia: the live book walked, or the cost model",
  demo: "Filled by a venue's demo account: real API, virtual money",
  live: "Real money",
};

const ROUTE_TONE: Record<FillRoute, ChipTone> = { live: "bad", demo: "accent", paper: "neutral" };

/**
 * Realised slippage against the cost model, per venue and route. This is the number that
 * says whether the backtests were fiction: if real fills cost far more than the
 * model assumed, every backtest built on the model was too optimistic.
 */
function SlippageSection({ rows }: { rows: SlippageRow[] }) {
  return (
    <Section
      title="Execution: realised vs modelled slippage"
      hint="What fills really cost against what the cost model expected. A ratio above 1.5x means backtests were too hopeful for that venue."
    >
      {rows.length === 0 ? (
        <Nothing icon={Gauge} title="No fills measured yet">
          Every fill (paper on a real price, demo, live) is measured against the price when the order was decided, and
          compared with what the cost model expected. The comparison means something after 30 fills per venue and route.
        </Nothing>
      ) : (
        <>
          <List>
            {rows.map((r) => {
              const route = r.route ?? "live";
              const extras = [
                !r.enough ? "fewer than 30 fills" : null,
                (r.liveFills ?? 0) > 0 ? `${r.liveFills} on a live book` : null,
                (r.exhausted ?? 0) > 0 ? `${r.exhausted} past the book` : null,
              ].filter(Boolean);
              return (
                <Row
                  key={`${r.venue}:${route}`}
                  label={
                    <span className="inline-flex flex-wrap items-center gap-1.5">
                      <span className="capitalize">{r.venue}</span>
                      <Badge tone={ROUTE_TONE[route]} title={ROUTE_HELP[route]}>
                        {route}
                      </Badge>
                    </span>
                  }
                  sub={
                    <span className="tabular">
                      {plural(r.fills, "fill")} · {num(r.medianRealisedBps, 1)} bps paid vs {num(r.medianModelledBps, 1)} modelled
                      {r.medianDriftBps !== undefined && ` · drift ${num(r.medianDriftBps, 1)} bps`}
                      {extras.length > 0 && <span className={(r.exhausted ?? 0) > 0 ? "text-warn" : undefined}> · {extras.join(", ")}</span>}
                    </span>
                  }
                  value={r.ratio === undefined ? "n/a" : `${num(r.ratio)}x`}
                  tone={r.ratio === undefined ? "plain" : r.ratio <= 1.5 ? "up" : "down"}
                  valueSub={r.ratio === undefined ? "no ratio yet" : r.ratio <= 1.5 ? "as modelled" : "costs more"}
                />
              );
            })}
          </List>
          <More title="How to read this">
            <p className="text-[13px] leading-relaxed text-muted">
              Positive bps cost money. Paper rows walk the exchange's live order book level by level when one less than a
              minute old exists, so they are honest about size; demo rows are what a venue's demo account really filled; live
              rows are real money. A live or demo ratio above 1.5x means real fills cost more than the model assumed, and
              every backtest using the model is too optimistic for that venue. Drift is how far the book had moved from the
              signal price before the order was priced.
            </p>
          </More>
        </>
      )}
    </Section>
  );
}

/** A strategy's gross, costs and net. A config that never traded has no ledger yet. */
function pnlOf(s: StrategyConfig): PnlBreakdown {
  return s.ledger?.pnl ?? breakdown(s.pnl, 0);
}
