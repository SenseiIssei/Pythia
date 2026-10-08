import { useCallback, useEffect, useState } from "react";
import { Microscope, RefreshCw } from "lucide-react";
import { Badge, Button, Card, EmptyState, Loading, Meter, Notice, PageHeader, Sparkline, Term } from "../components/ui";
import { liveMode } from "../live";
import {
  bandScale,
  costLine,
  forwardStatus,
  gatePct,
  labStatus,
  signedPct,
  type ForwardReport,
  type ForwardRow,
  type LabStatus,
  type PaperBook,
} from "../lab";
import { useAdvanced } from "../uiMode";

/** Plain-language names for the lab's paper books and reports. */
const BOOK_LABEL: Record<string, string> = {
  tsmom: "Momentum, 20 coins",
  tsmom_regime: "Momentum with BTC regime filter",
  tsmom_top20: "Momentum, 20 most traded coins each day",
  breakout_top10: "Breakout, 10 most traded coins each day",
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
};

const usd = (v: number, digits: number) =>
  `$${v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

/** A return drawn against the band its backtest expected over the same days. */
function BandBar({ row }: { row: ForwardRow }) {
  const e = row.expected;
  const ret = row.returnPct ?? 0;
  if (!e) {
    return (
      <div className="text-xs text-cyber-text-faint">
        <span className="font-mono text-cyber-text">{signedPct(row.returnPct)}</span> · no backtest range to compare with
      </div>
    );
  }
  const s = bandScale(ret, e);
  const dot = row.position === "below" ? "bg-warning" : row.position === "above" ? "bg-accent" : "bg-success";
  return (
    <div>
      <div className="relative h-3" aria-hidden>
        <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-cyber-border-bright" />
        <div className="absolute top-0 h-full w-px bg-cyber-text-faint" style={{ left: `${s.zero}%` }} title="zero" />
        <div
          className="absolute top-0.5 h-2 rounded-sm bg-accent/25"
          style={{ left: `${s.low}%`, width: `${Math.max(s.high - s.low, 0.5)}%` }}
        />
        <div className="absolute top-0.5 h-2 w-0.5 bg-accent/70" style={{ left: `${s.median}%` }} />
        <div
          className={`absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-cyber-surface ${dot}`}
          style={{ left: `${s.actual}%` }}
        />
      </div>
      <div className="mt-1 text-xs text-cyber-text-faint">
        <span className="font-mono text-cyber-text">{signedPct(ret)}</span> vs{" "}
        <Term k="Expected range">expected</Term>{" "}
        <span className="font-mono">
          {signedPct(e.lowPct)} to {signedPct(e.highPct)}
        </span>
        {e.method === "approximate" && " (approximate)"}
      </div>
    </div>
  );
}

function ForwardItem({ row, advanced }: { row: ForwardRow; advanced: boolean }) {
  const st = forwardStatus(row.status);
  const g = row.gate7;
  const pct = gatePct(g);
  const isAp = row.kind === "autopilot";
  const costs = costLine(row.costs);
  return (
    <div className="py-3">
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-0">
          <div className="font-medium text-cyber-text">
            {row.label || BOOK_LABEL[row.name] || row.name}
            {isAp && (
              <span className="ml-2 align-middle">
                <Badge tone="purple">{row.mode ? `${row.mode} autopilot` : "autopilot"}</Badge>
              </span>
            )}
          </div>
          {advanced && (
            <div className="break-words text-xs text-cyber-text-faint">
              {row.name}
              {row.variant ? ` · ${row.variant}` : ""}
              {row.since ? ` · since ${row.since}` : ""}
            </div>
          )}
        </div>
        <Badge tone={st.tone}>{st.label}</Badge>
      </div>
      <p className="mt-1 text-sm text-cyber-text-dim">{row.sentence}</p>
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        <BandBar row={row} />
        <div>
          <Meter pct={pct} tone={g.ready ? "green" : "neutral"} label={`${row.label}: progress to gate 7`} />
          <div className="mt-1 text-xs text-cyber-text-faint">
            <Term k="Gate 7">Gate 7</Term>:{" "}
            <span className="font-mono">
              {Math.min(g.days, g.daysNeeded)}/{g.daysNeeded}
            </span>{" "}
            days,{" "}
            <span className="font-mono">
              {Math.min(g.trades, g.tradesNeeded)}/{g.tradesNeeded}
            </span>{" "}
            {g.tradesLabel || "trades"}
          </div>
        </div>
      </div>
      {isAp && (
        <div className="mt-2 grid gap-x-4 gap-y-1 text-xs text-cyber-text-faint sm:grid-cols-2">
          {row.btcReturnPct != null && (
            <div>
              <Term k="Just holding Bitcoin">BTC held</Term> over the same time:{" "}
              <span className="font-mono text-cyber-text">{signedPct(row.btcReturnPct)}</span>
            </div>
          )}
          {row.equity != null && row.startEquity != null && (
            <div>
              Value <span className="font-mono text-cyber-text">{usd(row.equity, 2)}</span> of {usd(row.startEquity, 0)}
              {row.floorEquity != null && (
                <>
                  , <Term k="Floor">floor</Term> <span className="font-mono">{usd(row.floorEquity, 0)}</span>
                </>
              )}
            </div>
          )}
        </div>
      )}
      {!isAp && costs && (
        <div className="mt-2 text-xs text-cyber-text-faint">
          <Term k="Paper vs model costs">Costs</Term>: <span className="font-mono">{costs}</span>
        </div>
      )}
      {advanced && (
        <div className="mt-1 grid gap-x-4 gap-y-1 text-xs text-cyber-text-faint sm:grid-cols-2">
          {row.maxDdPct != null && (
            <div>
              <Term k="Worst dip">Worst dip</Term>{" "}
              <span className="font-mono">{row.maxDdPct.toFixed(2)} %</span>
              {row.expected?.ddP95Pct != null && (
                <span> (backtest, 19 in 20 stretches: under {row.expected.ddP95Pct.toFixed(2)} %)</span>
              )}
            </div>
          )}
          {row.turnover != null && (
            <div>
              Turnover <span className="font-mono">{row.turnover.toFixed(2)}x</span> of capital
            </div>
          )}
          {row.fundingPct != null && (
            <div>
              <Term k="Funding">Funding</Term> <span className="font-mono">{signedPct(row.fundingPct, 3)}</span>
            </div>
          )}
          {isAp && row.feesPctOfCapital != null && (
            <div>
              <Term k="Fees">Fees</Term> <span className="font-mono">{row.feesPctOfCapital.toFixed(2)} %</span> of capital
              {row.feesShareOfGross != null && (
                <>
                  , <Term k="Cost share">{(row.feesShareOfGross * 100).toFixed(0)} % of the gain before fees</Term>
                </>
              )}
            </div>
          )}
          {isAp && row.tradesPerDay != null && (
            <div>
              <Term k="Trades per day">Trades per day</Term>{" "}
              <span className="font-mono">{row.tradesPerDay.toFixed(1)}</span>
            </div>
          )}
          {isAp &&
            row.slippage.map((sl) => (
              <div key={sl.route}>
                <Term k="Slippage by route">Slippage, {sl.route}</Term>:{" "}
                <span className="font-mono">
                  {sl.medianRealisedBps?.toFixed(1) ?? "n/a"} vs {sl.medianModelledBps?.toFixed(1) ?? "n/a"} bps
                </span>{" "}
                modelled, {sl.fills} fill{sl.fills === 1 ? "" : "s"}
              </div>
            ))}
          {row.expected && <div className="sm:col-span-2">Range from: {row.expected.source}</div>}
        </div>
      )}
    </div>
  );
}

function ForwardSection({ f }: { f: ForwardReport }) {
  const advanced = useAdvanced();
  const rows = [...f.books, ...f.autopilots];
  return (
    <Card
      title="Forward test"
      subtitle={
        <>
          Every paper book and autopilot, held against what its backtest promised for the same number of days. Updated
          daily at 06:15 UTC{f.generated ? `, last on ${f.generated}` : ""}.
        </>
      }
    >
      <p className="text-sm text-cyber-text">{f.verdict}</p>
      {f.engine && !f.engine.reachable && (
        <p className="mt-1 text-xs text-warning">
          The autopilot engine did not answer when the report ran, so autopilots are missing this time.
        </p>
      )}
      <div className="mt-1 divide-y divide-cyber-border">
        {rows.map((r) => (
          <ForwardItem key={`${r.kind}:${r.name}`} row={r} advanced={advanced} />
        ))}
      </div>
    </Card>
  );
}

function Book({ b }: { b: PaperBook }) {
  const longs = b.lastRebalance.longs?.split(" ").filter(Boolean) ?? [];
  const shorts = b.lastRebalance.shorts?.split(" ").filter(Boolean) ?? [];
  const tone = b.returnPct >= 0 ? "green" : "red";
  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-bold text-cyber-text">{BOOK_LABEL[b.name] ?? b.name}</div>
          <div className="text-xs text-cyber-text-faint">
            {b.variant} · since {b.started} · {b.days} day{b.days === 1 ? "" : "s"}
          </div>
        </div>
        <div className={`shrink-0 whitespace-nowrap text-right text-lg font-bold tabular-nums ${tone === "green" ? "text-success" : "text-danger"}`}>
          {b.returnPct >= 0 ? "+" : ""}
          {b.returnPct.toFixed(2)} %
        </div>
      </div>
      <div className="mt-3">
        <Sparkline data={b.equity} tone={tone} height={56} />
      </div>
      {(longs.length > 0 || shorts.length > 0) && (
        <div className="mt-3 grid gap-1 text-xs">
          {longs.length > 0 && (
            <div>
              <span className="text-success">Long</span>{" "}
              <span className="text-cyber-text-dim">{longs.map((s) => s.replace(/USDT$/, "")).join(", ")}</span>
            </div>
          )}
          {shorts.length > 0 && (
            <div>
              <span className="text-danger">Short</span>{" "}
              <span className="text-cyber-text-dim">{shorts.map((s) => s.replace(/USDT$/, "")).join(", ")}</span>
            </div>
          )}
        </div>
      )}
      <div className="mt-3" title="Gate 7 of the Strategy Passport: 30 days of practice before real money">
        <div className="mb-1 flex justify-between text-xs text-cyber-text-faint">
          <span>Days of practice (30 needed for real money)</span>
          <span className="font-mono">{Math.min(b.days, 30)}/30</span>
        </div>
        <Meter pct={(Math.min(b.days, 30) / 30) * 100} tone={b.days >= 30 ? "green" : "neutral"} label="Days of practice" />
      </div>
    </Card>
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

  const header = (
    <PageHeader
      title="Lab"
      subtitle="Paper books running on real prices with play money, and what every experiment concluded"
    />
  );

  if (mode === "none") {
    return (
      <div className="animate-fade-in mx-auto max-w-5xl">
        {header}
        <Card>
          <EmptyState icon={Microscope} title="The lab needs the desktop app or a connected server">
            The paper books and experiment reports are read from the lab's data folder, which this browser version
            cannot reach.
          </EmptyState>
        </Card>
      </div>
    );
  }

  return (
    <div className="animate-fade-in mx-auto max-w-5xl space-y-4">
      {header}
      {!s && !err && <Loading>Reading the lab's data</Loading>}
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
        <Card
          title="Is everything running?"
          right={<Badge tone={s.health.ok ? "green" : "red"}>{s.health.ok ? "all good" : "needs a look"}</Badge>}
        >
          <div className="grid gap-x-6 gap-y-1 text-sm md:grid-cols-2">
            {s.health.checks.map((c) => (
              <div key={c.name} className="flex min-w-0 items-baseline gap-2">
                <span className={c.ok ? "text-success" : "text-danger"} aria-label={c.ok ? "fine" : "needs a look"}>
                  {c.ok ? "●" : "▲"}
                </span>
                <span className="text-cyber-text">{c.name}</span>
                <span className="truncate text-xs text-cyber-text-faint" title={c.detail}>
                  {c.detail}
                </span>
              </div>
            ))}
          </div>
          <div className="mt-2 text-xs text-cyber-text-faint">
            Checked {new Date(s.health.at).toLocaleString()} on the lab machine, every hour.
          </div>
        </Card>
      )}

      {s?.forward && <ForwardSection f={s.forward} />}

      {s && s.books.length > 0 && (
        <>
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <h2 className="font-mono text-sm font-bold text-accent">Paper books</h2>
              <p className="text-xs text-cyber-text-faint">Strategies trading real prices with play money, to see if the backtest holds.</p>
            </div>
            <Button tone="neutral" icon={RefreshCw} onClick={() => void refresh()}>
              Refresh
            </Button>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {s.books.map((b) => (
              <Book key={b.name} b={b} />
            ))}
          </div>
        </>
      )}

      {s && s.reports.length > 0 && (
        <Card title="What the experiments concluded">
          <div className="divide-y divide-cyber-border">
            {s.reports.map((r) => (
              <div key={r.name} className="grid gap-1 py-2.5 md:grid-cols-[220px_1fr]">
                <div>
                  <div className="text-sm font-medium text-cyber-text">{REPORT_LABEL[r.name] ?? r.name}</div>
                  <div className="text-xs text-cyber-text-faint">{new Date(r.updatedMs).toLocaleDateString()}</div>
                </div>
                <div className="text-sm text-cyber-text-dim">{r.verdict}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {s && s.found && (
        <p className="text-xs text-cyber-text-faint">
          Read from {s.dir}. <Badge tone="neutral">read-only</Badge>
        </p>
      )}
    </div>
  );
}
