import { useMemo } from "react";
import { GitFork } from "lucide-react";
import { useStore } from "../store";
import { Badge, Card, List, Notice, Page } from "../design";
import { KeyStats, Nothing, Row, Section, num, plural } from "../pagekit";
import { bunching, corrTint, corrWord, topPairs } from "../pagekit/insight";
import { correlationMatrix, concentration, type CorrMatrix } from "../lib/correlation";

export function Correlation() {
  const { history, historyTimes, positions, markets } = useStore();

  const symbolOf = useMemo(() => {
    const m = new Map(markets.map((x) => [x.id, x.symbol]));
    return (id: string) => m.get(id) ?? id.split(":").slice(1).join(":");
  }, [markets]);

  const corr = useMemo(() => correlationMatrix(history, historyTimes), [history, historyTimes]);
  const heldIds = useMemo(() => [...new Set(positions.map((p) => p.marketId))].filter((id) => corr.ids.includes(id)), [positions, corr]);
  const conc = useMemo(() => concentration(heldIds, corr), [heldIds, corr]);
  const pairs = useMemo(() => topPairs(corr, heldIds, 5, false), [corr, heldIds]);

  const title = "Correlation";
  const subtitle = "Whether your positions are really separate bets, or one bet in disguise: markets that move together fall together.";

  if (corr.ids.length < 2) {
    return (
      <Page title={title} subtitle={subtitle}>
        <Card>
          <Nothing icon={GitFork} title="Gathering price history">
            Correlations appear after about 20 price bars per market.
          </Nothing>
        </Card>
      </Page>
    );
  }

  const spread = bunching(conc.n, conc.effectiveBets);
  const short = (id: string) => symbolOf(id).replace("/USD", "");

  return (
    <Page title={title} subtitle={subtitle} wide>
      <KeyStats
        items={[
          {
            label: "Effective bets",
            value: conc.n >= 2 ? num(conc.effectiveBets, 1) : String(conc.n),
            tone: spread.tone,
            sub: conc.n >= 2 ? `You hold ${conc.n}. ${spread.word}.` : spread.word,
          },
          {
            label: "Open positions",
            value: String(conc.n),
            sub: `${plural(corr.ids.length, "market")} tracked`,
            help: "Markets it holds something in that have enough price history to compare.",
          },
          {
            label: "Avg |correlation|",
            value: conc.n >= 2 ? num(conc.avgAbsCorr) : "n/a",
            tone: conc.n < 2 ? "plain" : conc.avgAbsCorr > 0.6 ? "down" : conc.avgAbsCorr > 0.3 ? "warn" : "up",
            sub: conc.n >= 2 ? `held positions ${corrWord(conc.avgAbsCorr)}` : "across held positions",
          },
        ]}
      />

      {conc.n >= 2 && conc.effectiveBets < conc.n * 0.6 && (
        <Notice tone="warning" title="Your bets are bunched together">
          Your {conc.n} positions behave like only about {num(conc.effectiveBets, 1)} separate bets. A move against that
          group hits all of them at once.
        </Notice>
      )}

      {conc.unmeasured > 0 && (
        <Notice tone="info">
          {plural(conc.unmeasured, "pair")} of your positions can&apos;t be compared: one side runs on 5-minute candles and the
          other on live ticks (or the candles share too few times). They are counted as moving together here, and the risk
          manager does the same.
        </Notice>
      )}

      <Section
        title="Most alike"
        hint="The pairs that move most alike or most opposite, strongest first. Pairs you hold are marked."
        help="Correlation runs from 1 (move as one) through 0 (unrelated) to −1 (move opposite)."
      >
        {pairs.length === 0 ? (
          <Nothing icon={GitFork} title="No pairs can be compared yet" />
        ) : (
          <List>
            {pairs.map((p) => (
              <Row
                key={`${p.a}|${p.b}`}
                label={
                  <span className="inline-flex flex-wrap items-center gap-1.5">
                    <span className="break-all">
                      {short(p.a)} and {short(p.b)}
                    </span>
                    {p.held && <Badge tone="accent">both held</Badge>}
                  </span>
                }
                sub={corrWord(p.r)}
                value={num(p.r)}
                tone={p.r >= 0.7 ? "down" : p.r >= 0.4 ? "warn" : "plain"}
              />
            ))}
          </List>
        )}
      </Section>

      <Section
        title="Return Correlation Matrix"
        hint="Every market against every other. Darker red: they move together, so risk piles up. Green: they move opposite and balance each other."
        right={<Badge>{`${corr.ids.length}×${corr.ids.length}`}</Badge>}
      >
        <div className="-mx-1 overflow-x-auto px-1 pb-1">
          <div
            role="group"
            aria-label="Correlation of every pair of markets, times 100"
            className="inline-grid gap-px text-[11px]"
            style={{ gridTemplateColumns: `minmax(64px,auto) repeat(${corr.ids.length}, 30px)` }}
          >
            <div />
            {corr.ids.map((id) => (
              <div key={id} className="flex h-16 items-end justify-center pb-1">
                <span className="origin-bottom-left -rotate-90 whitespace-nowrap text-muted">{short(id)}</span>
              </div>
            ))}
            {corr.ids.map((rowId, i) => (
              <MatrixRow key={rowId} rowId={rowId} i={i} corr={corr} symbolOf={symbolOf} held={heldIds.includes(rowId)} heldIds={heldIds} />
            ))}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-muted">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded" style={{ background: corrTint(0.9) }} aria-hidden /> move together
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded" style={{ background: corrTint(-0.9) }} aria-hidden /> move opposite
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded border border-line" aria-hidden /> can&apos;t compare (candles against ticks)
          </span>
        </div>
        <p className="mt-1 text-[13px] text-muted">Outlined squares and bold names: markets you hold. Numbers are correlation × 100.</p>
      </Section>
    </Page>
  );
}

function MatrixRow({
  rowId,
  i,
  corr,
  symbolOf,
  held,
  heldIds,
}: {
  rowId: string;
  i: number;
  corr: CorrMatrix;
  symbolOf: (id: string) => string;
  held: boolean;
  heldIds: string[];
}) {
  return (
    <>
      <div className={`flex items-center justify-end pr-2 ${held ? "font-semibold text-ink" : "text-muted"}`}>
        {symbolOf(rowId).replace("/USD", "")}
      </div>
      {corr.ids.map((colId, j) => {
        const r = corr.matrix[i][j];
        const both = held && heldIds.includes(colId);
        const pair = `${symbolOf(rowId)} vs ${symbolOf(colId)}`;
        return (
          <div
            key={colId}
            title={r === null ? `${pair}: can't be compared in time (candles against ticks)` : `${pair}: ${num(r)}, ${corrWord(r)}`}
            className={`tabular flex h-[30px] items-center justify-center rounded-[3px] text-ink ${i === j ? "bg-surface-2" : ""} ${r === null && i !== j ? "border border-line" : ""}`}
            style={{
              background: i === j || r === null ? undefined : corrTint(r),
              outline: both && i !== j ? "1.5px solid var(--color-text)" : undefined,
              outlineOffset: both && i !== j ? "-1.5px" : undefined,
            }}
          >
            {i === j ? "" : r === null ? "-" : num(r * 100, 0)}
          </div>
        );
      })}
    </>
  );
}
