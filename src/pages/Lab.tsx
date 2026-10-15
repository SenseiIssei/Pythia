import { useCallback, useEffect, useState } from "react";
import { Microscope, RefreshCw } from "lucide-react";
import { Badge, Button, Card, List, Notice, Page, Sparkline, changeTone, money, signedPct } from "../design";
import { KeyStats, LoadingRows, Meter, Nothing, Row, Section, Term, num, pct, plural, type Stat } from "../pagekit";
import { coinName, forwardTally, labChip } from "../pagekit/insight";
import { liveMode } from "../live";
import {
  bandScale,
  costLine,
  forwardStatus,
  gatePct,
  labStatus,
  type ForwardReport,
  type ForwardRow,
  type LabStatus,
  type LearnDigest,
  type PaperBook,
} from "../lab";
import { useAdvanced } from "../uiMode";

/** Plain-language names for the lab's paper books and reports. */
const BOOK_LABEL: Record<string, string> = {
  tsmom: "Momentum, 20 coins",
  tsmom_regime: "Momentum with BTC regime filter",
  tsmom_top20: "Momentum, 20 most traded coins each day",
  breakout_top10: "Breakout, 10 most traded coins each day",
  tsmom_tranches: "Momentum in seven weekly tranches, 20 most traded coins each day",
  m4_ls: "M4 market-neutral (perps)",
  picks_ls: "M2 market-neutral (perps)",
  picks_ls_v2: "M2 v2 market-neutral (perps)",
};
const REPORT_LABEL: Record<string, string> = {
  vol_1h: "M1 · next-hour volatility",
  picks: "M2 · coin picks",
  picks_v2: "M2 v2 · picks with perp features",
  picks_ls: "M2 market-neutral",
  picks_ls_v2: "M2 v2 market-neutral",
  tsmom: "Momentum, round one",
  momentum2: "Momentum, regime and rotation",
  momentum_m2: "Momentum with M2 filter",
  spread: "Kraken vs Binance spread",
  carry: "Funding carry",
  meta_breakout: "Meta-labeled breakout",
  paper_review: "Paper books vs backtests",
  forward: "Forward tests, daily",
  learn: "Learning loop, nightly",
};

/** A return drawn against the band its backtest expected over the same days. */
function BandBar({ row }: { row: ForwardRow }) {
  const e = row.expected;
  const ret = row.returnPct ?? 0;
  if (!e) {
    return (
      <div className="text-[13px] text-muted">
        <span className={`tabular font-semibold ${toneText(row.returnPct)}`}>{signedPct(row.returnPct)}</span> · no backtest range to compare with
      </div>
    );
  }
  const s = bandScale(ret, e);
  const dot = row.position === "below" ? "bg-warn" : row.position === "above" ? "bg-accent" : "bg-up";
  const where = row.position === "below" ? "below the range" : row.position === "above" ? "above the range" : row.position === "inside" ? "inside the range" : "";
  return (
    <div>
      <div className="relative h-3" aria-hidden>
        <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-line-strong" />
        <div className="absolute top-0 h-full w-px bg-faint" style={{ left: `${s.zero}%` }} title="zero" />
        <div className="absolute top-0.5 h-2 rounded-sm bg-accent/20" style={{ left: `${s.low}%`, width: `${Math.max(s.high - s.low, 0.5)}%` }} />
        <div className="absolute top-0.5 h-2 w-0.5 bg-accent/60" style={{ left: `${s.median}%` }} />
        <div
          className={`absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface ${dot}`}
          style={{ left: `${s.actual}%` }}
        />
      </div>
      <div className="mt-1 text-[13px] text-muted">
        <span className={`tabular font-semibold ${toneText(ret)}`}>{signedPct(ret)}</span> vs <Term k="Expected range">expected</Term>{" "}
        <span className="tabular">
          {signedPct(e.lowPct)} to {signedPct(e.highPct)}
        </span>
        {e.method === "approximate" && " (approximate)"}
        {where && `, ${where}`}
      </div>
    </div>
  );
}

function toneText(v: number | null | undefined): string {
  const t = changeTone(v);
  return t === "up" ? "text-up" : t === "down" ? "text-down" : "text-ink";
}

/** The nightly learning loop: what it changed and why. It only reads the engine. */
function LearnSection({ d }: { d: LearnDigest }) {
  const failed = d.steps.filter((x) => x.status === "failed");
  return (
    <Section
      title="What the system learned last night"
      hint="It updates evidence, costs and models within fixed bounds. It cannot change settings, arm live or move money."
      right={<Badge tone={failed.length ? "bad" : "good"}>{failed.length ? `${failed.length} step failed` : d.generated}</Badge>}
    >
      <p className="text-[15px] leading-relaxed text-ink">{d.headline}</p>
      {d.changes.length > 0 && (
        <List className="mt-2">
          {d.changes.map((c, i) => (
            <div key={i} className="py-3">
              <div className="flex items-start justify-between gap-3">
                <span className="min-w-0 text-[15px] font-semibold text-ink">{c.what}</span>
                <Badge>{c.area}</Badge>
              </div>
              {c.why && <p className="mt-0.5 text-[13px] text-muted">{c.why}</p>}
            </div>
          ))}
        </List>
      )}
      {d.autopilots.length > 0 && (
        <List className="mt-2 border-t border-line">
          {d.autopilots.map((a) => (
            <Row
              key={a.id}
              label={a.name}
              sub={
                <span className="tabular">
                  BTC {signedPct(a.btcDayPct)} today, {signedPct(a.btcTotalPct)} since start
                </span>
              }
              value={signedPct(a.pnlDayPct)}
              tone={changeTone(a.pnlDayPct)}
              valueSub={<span className="tabular">{signedPct(a.pnlTotalPct)} since start</span>}
            />
          ))}
        </List>
      )}
      {failed.map((x) => (
        <Notice key={x.step} tone="danger" className="mt-2">
          <span className="break-words">
            {x.step}: {x.detail}
          </span>
        </Notice>
      ))}
    </Section>
  );
}

function ForwardItem({ row, advanced }: { row: ForwardRow; advanced: boolean }) {
  const st = forwardStatus(row.status);
  const g = row.gate7;
  const gp = gatePct(g);
  const isAp = row.kind === "autopilot";
  const costs = costLine(row.costs);
  const name = row.label || BOOK_LABEL[row.name] || row.name;
  return (
    <div className="py-4">
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[15px] font-semibold text-ink">{name}</span>
            {isAp && <Badge tone="accent">{row.mode ? `${row.mode} autopilot` : "autopilot"}</Badge>}
          </div>
          {advanced && (
            <div className="break-all text-[13px] text-faint">
              {row.name}
              {row.variant ? ` · ${row.variant}` : ""}
              {row.since ? ` · since ${row.since}` : ""}
            </div>
          )}
        </div>
        <Badge tone={labChip(st.tone)}>{st.label}</Badge>
      </div>
      <p className="mt-1 text-[15px] leading-relaxed text-ink">{row.sentence}</p>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <BandBar row={row} />
        <div>
          <Meter pct={gp} label={`${name}: progress to gate 7`} />
          <div className="mt-1 text-[13px] text-muted">
            <Term k="Gate 7">Gate 7</Term>:{" "}
            <span className="tabular">
              {Math.min(g.days, g.daysNeeded)}/{g.daysNeeded}
            </span>{" "}
            days,{" "}
            <span className="tabular">
              {Math.min(g.trades, g.tradesNeeded)}/{g.tradesNeeded}
            </span>{" "}
            {g.tradesLabel || "trades"}
            {g.ready && <span className="font-semibold text-up">, passed</span>}
          </div>
        </div>
      </div>
      {isAp && (row.btcReturnPct != null || (row.equity != null && row.startEquity != null)) && (
        <List className="mt-2">
          {row.btcReturnPct != null && (
            <Row
              label={<Term k="Just holding Bitcoin">Just holding Bitcoin</Term>}
              sub="over the same time"
              value={signedPct(row.btcReturnPct)}
              tone={changeTone(row.btcReturnPct)}
            />
          )}
          {row.equity != null && row.startEquity != null && (
            <Row
              label="Value now"
              sub={
                <>
                  of {money(row.startEquity, 0)} at the start
                  {row.floorEquity != null && (
                    <>
                      , <Term k="Floor">floor</Term> <span className="tabular">{money(row.floorEquity, 0)}</span>
                    </>
                  )}
                </>
              }
              value={money(row.equity, 2)}
            />
          )}
        </List>
      )}
      {!isAp && costs && (
        <div className="mt-2 text-[13px] text-muted">
          <Term k="Paper vs model costs">Costs</Term>: <span className="tabular">{costs}</span>
        </div>
      )}
      {advanced && (
        <div className="tabular mt-2 grid gap-x-4 gap-y-1 text-[13px] text-muted sm:grid-cols-2">
          {row.maxDdPct != null && (
            <div>
              <Term k="Worst dip">Worst dip</Term> {pct(row.maxDdPct, 2)}
              {row.expected?.ddP95Pct != null && <span> (backtest, 19 in 20 stretches: under {pct(row.expected.ddP95Pct, 2)})</span>}
            </div>
          )}
          {row.turnover != null && <div>Turnover {num(row.turnover)}x of capital</div>}
          {row.fundingPct != null && (
            <div>
              <Term k="Funding">Funding</Term> {signedPct(row.fundingPct, 3)}
            </div>
          )}
          {isAp && row.feesPctOfCapital != null && (
            <div>
              <Term k="Fees">Fees</Term> {pct(row.feesPctOfCapital, 2)} of capital
              {row.feesShareOfGross != null && (
                <>
                  , <Term k="Cost share">{pct(row.feesShareOfGross * 100, 0)} of the gain before fees</Term>
                </>
              )}
            </div>
          )}
          {isAp && row.tradesPerDay != null && (
            <div>
              <Term k="Trades per day">Trades per day</Term> {num(row.tradesPerDay, 1)}
            </div>
          )}
          {isAp &&
            row.slippage.map((sl) => (
              <div key={sl.route}>
                <Term k="Slippage by route">Slippage, {sl.route}</Term>: {sl.medianRealisedBps != null ? num(sl.medianRealisedBps, 1) : "n/a"} vs{" "}
                {sl.medianModelledBps != null ? num(sl.medianModelledBps, 1) : "n/a"} bps modelled, {plural(sl.fills, "fill")}
              </div>
            ))}
          {row.expected && <div className="break-words sm:col-span-2">Range from: {row.expected.source}</div>}
        </div>
      )}
    </div>
  );
}

function ForwardSection({ f }: { f: ForwardReport }) {
  const advanced = useAdvanced();
  const rows = [...f.books, ...f.autopilots];
  return (
    <Section
      title="Forward test"
      hint={
        <>
          Every paper book and autopilot, held against what its backtest promised for the same number of days. Updated daily at
          06:15 UTC{f.generated ? `, last on ${f.generated}` : ""}.
        </>
      }
    >
      <p className="text-[15px] leading-relaxed text-ink">{f.verdict}</p>
      {f.engine && !f.engine.reachable && (
        <Notice tone="warning" className="mt-2">
          The autopilot engine did not answer when the report ran, so autopilots are missing this time.
        </Notice>
      )}
      {rows.length === 0 ? (
        <Nothing title="No forward tests yet">Books and autopilots show here once the daily report has run.</Nothing>
      ) : (
        <List className="mt-1">
          {rows.map((r) => (
            <ForwardItem key={`${r.kind}:${r.name}`} row={r} advanced={advanced} />
          ))}
        </List>
      )}
    </Section>
  );
}

function BookRow({ b }: { b: PaperBook }) {
  const longs = b.lastRebalance.longs?.split(" ").filter(Boolean) ?? [];
  const shorts = b.lastRebalance.shorts?.split(" ").filter(Boolean) ?? [];
  const tone = changeTone(b.returnPct);
  return (
    <div className="py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[15px] font-semibold text-ink">{BOOK_LABEL[b.name] ?? b.name}</div>
          <div className="break-words text-[13px] text-muted">
            {b.variant} · since {b.started} · {plural(b.days, "day")}
          </div>
        </div>
        <div className={`tabular shrink-0 whitespace-nowrap text-right text-[17px] font-semibold ${toneText(b.returnPct)}`}>{signedPct(b.returnPct)}</div>
      </div>
      <div className="mt-3">
        <Sparkline data={b.equity} tone={tone} height={48} fill label={`${BOOK_LABEL[b.name] ?? b.name}: value over time`} />
      </div>
      {(longs.length > 0 || shorts.length > 0) && (
        <div className="mt-3 space-y-1 text-[13px]">
          {longs.length > 0 && (
            <div className="break-words">
              <span className="font-semibold text-ink">Long</span> <span className="text-muted">{longs.map(coinName).join(", ")}</span>
            </div>
          )}
          {shorts.length > 0 && (
            <div className="break-words">
              <span className="font-semibold text-ink">Short</span> <span className="text-muted">{shorts.map(coinName).join(", ")}</span>
            </div>
          )}
        </div>
      )}
      <div className="mt-3" title="Gate 7 of the Strategy Passport: 30 days of practice before real money">
        <div className="mb-1 flex justify-between gap-2 text-[13px] text-muted">
          <span>Days of practice (30 needed for real money)</span>
          <span className="tabular">{Math.min(b.days, 30)}/30</span>
        </div>
        <Meter pct={(Math.min(b.days, 30) / 30) * 100} label="Days of practice" />
      </div>
    </div>
  );
}

export function Lab() {
  const mode = liveMode();
  const [s, setS] = useState<LabStatus | null>(null);
  const [err, setErr] = useState("");

  const refresh = useCallback(async () => {
    try {
      setS(await labStatus());
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (mode !== "none") void refresh();
  }, [mode, refresh]);

  const title = "Lab";
  const subtitle = "Paper books running on real prices with play money, and what every experiment concluded.";

  if (mode === "none") {
    return (
      <Page title={title} subtitle={subtitle}>
        <Card>
          <Nothing icon={Microscope} title="The lab needs the desktop app or a connected server">
            The paper books and experiment reports are read from the lab's data folder, which this browser version cannot
            reach.
          </Nothing>
        </Card>
      </Page>
    );
  }

  const forwardRows = s?.forward ? [...s.forward.books, ...s.forward.autopilots] : [];
  const tally = forwardTally(forwardRows);
  const stats: Stat[] = [];
  if (tally.total > 0) {
    stats.push({
      label: "In line or better",
      value: `${tally.fine} of ${tally.total}`,
      tone: tally.watch > 0 ? "warn" : "plain",
      sub: tally.watch > 0 ? `${plural(tally.watch, "test")} worth watching` : "forward tests matching their backtest",
      help: "Paper books and autopilots whose result sits inside or above the range their backtest expected.",
    });
    stats.push({
      label: "Passed gate 7",
      value: String(tally.ready),
      sub: "enough days and trades for real money",
      help: "Gate 7 of the Strategy Passport: a month of practice on real prices before real money.",
    });
  } else if (s && s.books.length > 0) {
    stats.push({ label: "Paper books", value: String(s.books.length), sub: "trading real prices with play money" });
  }
  if (s?.health) {
    stats.push({
      label: "Lab health",
      value: s.health.ok ? "All good" : "Needs a look",
      tone: s.health.ok ? "up" : "down",
      sub: `${s.health.checks.filter((c) => c.ok).length} of ${s.health.checks.length} checks fine`,
      help: "The lab machine checks every job once an hour.",
    });
  }

  return (
    <Page
      title={title}
      subtitle={subtitle}
      right={
        <Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => void refresh()}>
          Refresh
        </Button>
      }
    >
      {stats.length > 0 && <KeyStats items={stats} />}
      {!s && !err && (
        <Card>
          <LoadingRows label="Reading the lab's data" />
        </Card>
      )}
      {err && (
        <Notice tone="danger" title="Could not read the lab">
          {err}
        </Notice>
      )}
      {s && !s.found && (
        <Notice tone="warning" title="No lab data found">
          Set PYTHIA_DATA (or PYTHIA_MODELS) to the folder the lab syncs to, for example the synced PythiaData folder.
        </Notice>
      )}

      {s?.health && (
        <Section
          title="Is everything running?"
          hint={`Checked ${new Date(s.health.at).toLocaleString()} on the lab machine, every hour.`}
          right={<Badge tone={s.health.ok ? "good" : "bad"}>{s.health.ok ? "all good" : "needs a look"}</Badge>}
        >
          <List>
            {s.health.checks.map((c) => (
              <Row
                key={c.name}
                label={c.name}
                sub={<span className="break-words">{c.detail}</span>}
                value={c.ok ? "Fine" : "Needs a look"}
                tone={c.ok ? "up" : "down"}
              />
            ))}
          </List>
        </Section>
      )}

      {s?.forward && <ForwardSection f={s.forward} />}

      {s?.learn && <LearnSection d={s.learn} />}

      {s && s.books.length > 0 && (
        <Section title="Paper books" hint="Strategies trading real prices with play money, to see if the backtest holds.">
          <List>
            {s.books.map((b) => (
              <BookRow key={b.name} b={b} />
            ))}
          </List>
        </Section>
      )}

      {s && s.reports.length > 0 && (
        <Section title="What the experiments concluded" hint="Each experiment's verdict, newest write-up date under its name.">
          <List>
            {s.reports.map((r) => (
              <div key={r.name} className="py-3">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="min-w-0 text-[15px] font-semibold text-ink">{REPORT_LABEL[r.name] ?? r.name}</span>
                  <span className="tabular shrink-0 text-[13px] text-faint">{new Date(r.updatedMs).toLocaleDateString()}</span>
                </div>
                <p className="mt-0.5 text-[15px] leading-relaxed text-muted">{r.verdict}</p>
              </div>
            ))}
          </List>
        </Section>
      )}

      {s && s.found && (
        <p className="flex flex-wrap items-center gap-2 px-1 text-[13px] text-muted">
          <span className="break-all">Read from {s.dir}.</span> <Badge>read-only</Badge>
        </p>
      )}
    </Page>
  );
}
