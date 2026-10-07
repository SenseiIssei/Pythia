import { useMemo } from "react";
import { Layers, GitFork } from "lucide-react";
import { useStore } from "../store";
import { Card, PageHeader, StatCard, Badge, EmptyState, Notice } from "../components/ui";
import { correlationMatrix, concentration } from "../lib/correlation";

// diverging colour: +1 (correlated → concentration risk) warm, 0 neutral, -1 cool
function corrColor(r: number): string {
  if (r >= 0) {
    const a = Math.min(1, r);
    return `rgba(239,68,68,${(0.12 + a * 0.6).toFixed(3)})`; // red-ish
  }
  const a = Math.min(1, -r);
  return `rgba(34,197,94,${(0.12 + a * 0.5).toFixed(3)})`; // green-ish
}

export function Correlation() {
  const { history, positions, markets } = useStore();

  const symbolOf = useMemo(() => {
    const m = new Map(markets.map((x) => [x.id, x.symbol]));
    return (id: string) => m.get(id) ?? id.split(":").slice(1).join(":");
  }, [markets]);

  const corr = useMemo(() => correlationMatrix(history), [history]);
  const heldIds = useMemo(() => [...new Set(positions.map((p) => p.marketId))].filter((id) => corr.ids.includes(id)), [positions, corr]);
  const conc = useMemo(() => concentration(heldIds, corr), [heldIds, corr]);

  const header = (
    <PageHeader
      title="Correlation"
      subtitle="Whether your positions are really separate bets, or one bet in disguise: markets that move together fall together."
    />
  );

  if (corr.ids.length < 2) {
    return (
      <div className="animate-fade-in mx-auto max-w-6xl">
        {header}
        <Card>
          <EmptyState icon={GitFork} title="Gathering price history">
            Correlations appear after about 20 price bars per market.
          </EmptyState>
        </Card>
      </div>
    );
  }

  return (
    <div className="animate-fade-in mx-auto max-w-6xl">
      {header}

      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label="Open positions" value={String(conc.n)} icon={Layers} sub={`${corr.ids.length} markets tracked`} />
        <StatCard
          label="Avg |correlation|"
          value={conc.n >= 2 ? conc.avgAbsCorr.toFixed(2) : "-"}
          icon={GitFork}
          tone={conc.n < 2 ? "neutral" : conc.avgAbsCorr > 0.6 ? "red" : conc.avgAbsCorr > 0.3 ? "amber" : "green"}
          sub="across held positions"
        />
        <StatCard
          label="Effective bets"
          value={conc.n >= 2 ? conc.effectiveBets.toFixed(1) : String(conc.n)}
          icon={GitFork}
          tone={conc.n < 2 ? "neutral" : conc.effectiveBets < conc.n * 0.5 ? "red" : "green"}
          sub={conc.n >= 2 ? `you hold ${conc.n}, worth about ${conc.effectiveBets.toFixed(1)} separate bets` : "needs 2 or more positions"}
        />
      </div>

      {conc.n >= 2 && conc.effectiveBets < conc.n * 0.6 && (
        <Notice tone="warning" title="Your bets are bunched together" className="mb-4">
          Your {conc.n} positions behave like only about {conc.effectiveBets.toFixed(1)} separate bets. A move against
          that group hits all of them at once.
        </Notice>
      )}

      <Card title="Return Correlation Matrix" right={<Badge tone="neutral">{corr.ids.length}×{corr.ids.length}</Badge>}>
        <div className="-mx-1 overflow-x-auto px-1">
          <div
            className="inline-grid gap-px text-[10px]"
            style={{ gridTemplateColumns: `minmax(64px,auto) repeat(${corr.ids.length}, 28px)` }}
          >
            <div />
            {corr.ids.map((id) => (
              <div key={id} className="flex h-16 items-end justify-center pb-1">
                <span className="origin-bottom-left -rotate-90 whitespace-nowrap text-cyber-text-dim">{symbolOf(id).replace("/USD", "")}</span>
              </div>
            ))}
            {corr.ids.map((rowId, i) => (
              <Row key={rowId} rowId={rowId} i={i} corr={corr} symbolOf={symbolOf} held={heldIds.includes(rowId)} heldIds={heldIds} />
            ))}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-cyber-text-faint">
          <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded" style={{ background: corrColor(0.9) }} /> move together (risk piles up)</span>
          <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded" style={{ background: corrColor(-0.9) }} /> move opposite (they balance)</span>
          <span>Outlined squares: two markets you hold. Numbers are correlation × 100.</span>
        </div>
      </Card>
    </div>
  );
}

function Row({
  rowId,
  i,
  corr,
  symbolOf,
  held,
  heldIds,
}: {
  rowId: string;
  i: number;
  corr: { ids: string[]; matrix: number[][] };
  symbolOf: (id: string) => string;
  held: boolean;
  heldIds: string[];
}) {
  return (
    <>
      <div className={`flex items-center justify-end pr-2 font-mono ${held ? "text-accent" : "text-cyber-text-dim"}`}>
        {symbolOf(rowId).replace("/USD", "")}
      </div>
      {corr.ids.map((colId, j) => {
        const r = corr.matrix[i][j];
        const both = held && heldIds.includes(colId);
        return (
          <div
            key={colId}
            title={`${symbolOf(rowId)} vs ${symbolOf(colId)}: ${r.toFixed(2)}`}
            className="flex h-7 items-center justify-center"
            style={{ background: i === j ? "rgba(0,240,255,0.15)" : corrColor(r), outline: both && i !== j ? "1px solid rgba(0,240,255,0.5)" : undefined }}
          >
            <span className="text-cyber-text/70">{i === j ? "" : Math.round(r * 100)}</span>
          </div>
        );
      })}
    </>
  );
}
