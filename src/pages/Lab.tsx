import { useCallback, useEffect, useState } from "react";
import { Microscope, RefreshCw } from "lucide-react";
import { Badge, Button, Card, EmptyState, Loading, Meter, Notice, PageHeader, Sparkline } from "../components/ui";
import { liveMode } from "../live";
import { labStatus, type LabStatus, type PaperBook } from "../lab";

/** Plain-language names for the lab's paper books and reports. */
const BOOK_LABEL: Record<string, string> = {
  tsmom: "Momentum, 20 coins",
  tsmom_regime: "Momentum with BTC regime filter",
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
};

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
