import { useMemo } from "react";
import { Layers, GitFork } from "lucide-react";
import { useStore } from "../store";
import { Card, PageHeader, StatCard, Badge } from "../components/ui";
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

  if (corr.ids.length < 2) {
    return (
      <div className="animate-fade-in">
        <PageHeader title="Correlation" subtitle="How correlated your markets & positions really are" />
        <Card>
          <div className="py-6 text-center text-sm text-cyber-text-faint">Gathering price history… correlations appear after ~20 bars per market.</div>
        </Card>
      </div>
    );
  }

  return (
    <div className="animate-fade-in">
      <PageHeader title="Correlation" subtitle="How correlated your markets & positions really are" />

      <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-3">
        <StatCard label="Open positions" value={String(conc.n)} icon={Layers} tone="cyan" sub={`${corr.ids.length} markets tracked`} />
        <StatCard
          label="Avg |correlation|"
          value={conc.n >= 2 ? conc.avgAbsCorr.toFixed(2) : "—"}
          icon={GitFork}
          tone={conc.avgAbsCorr > 0.6 ? "red" : conc.avgAbsCorr > 0.3 ? "purple" : "green"}
          sub="across held positions"
        />
        <StatCard
          label="Effective bets"
          value={conc.n >= 2 ? conc.effectiveBets.toFixed(1) : String(conc.n)}
          icon={GitFork}
          tone={conc.n >= 2 && conc.effectiveBets < conc.n * 0.5 ? "red" : "green"}
          sub={conc.n >= 2 ? `you hold ${conc.n}, worth ~${conc.effectiveBets.toFixed(1)} independent` : "need 2+ positions"}
        />
      </div>

      {conc.n >= 2 && conc.effectiveBets < conc.n * 0.6 && (
        <Card className="mb-4 border-danger/30 bg-danger/5">
          <div className="text-sm text-danger">
            ⚠ Concentration warning — your {conc.n} positions behave like only ~{conc.effectiveBets.toFixed(1)} independent bets.
            A move against that cluster hits all of them at once.
          </div>
        </Card>
      )}

      <Card title="Return Correlation Matrix" right={<Badge tone="neutral">{corr.ids.length}×{corr.ids.length}</Badge>}>
        <div className="overflow-x-auto">
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
        <div className="mt-3 flex items-center gap-4 text-xs text-cyber-text-faint">
          <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded" style={{ background: corrColor(0.9) }} /> correlated (risk)</span>
          <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded" style={{ background: corrColor(-0.9) }} /> inversely (diversifying)</span>
          <span>· rows/cols outlined = markets you hold</span>
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
