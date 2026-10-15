// M2 "Picks" on the Models page: the weekly coin ranking in shadow mode.
// Read-only apart from "Rank now", which only asks the engine to rank and record.

import { useState } from "react";
import { Play } from "lucide-react";
import { Badge, Button, List, Notice } from "../design";
import { More, Row, Section, num, plural, share } from "../pagekit";
import { coinName, driftChip, icTone, signedNum } from "../pagekit/insight";
import { runPicks, type FeatureDrift, type PickView, type PicksStatus } from "../ml";

const NONE = "not yet";
const fmtDate = (ms: number) => new Date(ms).toLocaleDateString();
const fmtIc = (v: number | null | undefined) => (v === null || v === undefined ? NONE : num(v, 3));

function PickList({ title, picks }: { title: string; picks: PickView[] }) {
  return (
    <div className="min-w-0">
      <h3 className="text-[13px] font-medium text-muted">{title}</h3>
      <List>
        {picks.map((p) => (
          <Row
            key={p.symbol}
            label={
              <span>
                <span className="tabular mr-2 text-muted">{p.rank}.</span>
                <span className="break-all">{coinName(p.symbol)}</span>
              </span>
            }
            sub={p.perp ? undefined : "no perp"}
            value={num(p.percentile, 0)}
          />
        ))}
      </List>
    </div>
  );
}

/**
 * Every model input against the range it was trained on, as rows with words.
 * Shared by the volatility model and the coin ranking.
 */
export function DriftRows({ drift }: { drift: FeatureDrift[] }) {
  return (
    <List>
      {drift.map((d) => {
        const c = driftChip(d.level);
        return (
          <Row
            key={d.feature}
            label={<span className="break-all">{d.feature}</span>}
            sub={`PSI ${num(d.psi)}`}
            value={<Badge tone={c.tone}>{c.word}</Badge>}
            valueSub={`${num(d.outsidePct, 1)}% outside`}
          />
        );
      })}
    </List>
  );
}

export function PicksPanel({ p, onChanged }: { p: PicksStatus; onChanged: () => void }) {
  const [asked, setAsked] = useState(false);
  const [err, setErr] = useState("");
  const m = p.model;
  const sh = p.shadow;
  const live = sh.rankIc;
  const lab = m?.labRankIc ?? null;
  const latest = p.latest;
  const drifted = p.drift.filter((d) => d.level === "drift");
  const notes = [...p.engineNotes, ...(latest?.notes ?? [])];

  const rankNow = async () => {
    try {
      await runPicks();
      setAsked(true);
      setErr("");
      setTimeout(onChanged, 2_000);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <>
      <Section
        title="Weekly coin ranking (M2)"
        hint="Ranks every liquid Binance coin by how it is likely to do over the next seven days compared with the others. It says which coins should beat or lag the rest, not whether the market as a whole goes up."
        right={
          <>
            <Badge tone="accent">shadow mode</Badge>
            {m && (
              <Button variant="secondary" size="sm" icon={Play} onClick={() => void rankNow()} disabled={p.running}>
                {p.running ? "Running" : "Rank now"}
              </Button>
            )}
          </>
        }
      >
        {m && (
          <p className="text-[15px] leading-relaxed text-ink">
            Version {m.version}, {m.trees} trees, trained on data up to {fmtDate(m.trainToMs)}. In the lab its ranking agreed
            with the following week by a Rank-IC of <span className="tabular font-semibold">{fmtIc(lab)}</span> out of sample
            {m.labRankIcLiquid50 !== null && <> ({num(m.labRankIcLiquid50, 3)} among the 50 most liquid coins)</>}. It is ranked
            once a week and scored when that week is over; nothing is traded on it.
          </p>
        )}
        {p.state !== "live" && (
          <Notice
            tone={p.state === "rejected" ? "danger" : "warning"}
            title={p.state === "rejected" ? "Model refused" : p.state === "warmingUp" ? "Warming up" : "No model"}
            className={m ? "mt-3" : undefined}
          >
            {p.message}
          </Notice>
        )}
        {p.state === "live" && <p className="mt-2 text-[13px] text-muted">{p.message}</p>}
        {asked && !p.running && <p className="mt-1 text-[13px] text-muted">Asked for a ranking; it takes a few minutes.</p>}
        {err && (
          <Notice tone="danger" className="mt-2">
            {err}
          </Notice>
        )}

        {m && (
          <List className="mt-3 border-t border-line">
            <Row
              label="Ranking skill live"
              sub="Rank-IC: 1 is a perfect order, 0 no relation"
              help="How well the live ranking's order matched the coins' real seven-day returns. Half the backtest's number or more is a good sign."
              value={fmtIc(live)}
              tone={icTone(live, lab)}
              valueSub={lab === null ? undefined : `backtest ${num(lab, 3)}`}
            />
            <Row
              label="Last 8 weeks"
              sub="The same score over the recent weeks only"
              value={fmtIc(sh.rankIcRecent)}
              valueSub={sh.rankIcT === null ? "t-statistic after three weeks" : `t ${num(sh.rankIcT, 1)} over all weeks`}
            />
            <Row
              label="Weeks right"
              sub="Weeks with a positive Rank-IC"
              value={sh.hitRate === null ? NONE : share(sh.hitRate)}
            />
            <Row
              label="Weeks scored live"
              sub={sh.sinceMs ? `since ${fmtDate(sh.sinceMs)}` : "first score a week after the first ranking"}
              value={String(sh.weeks)}
            />
          </List>
        )}
      </Section>

      {latest && (
        <Section
          title={`Ranking of ${fmtDate(latest.dayMs)}`}
          hint={
            <>
              For the week after. {latest.coins} coins ranked, {latest.withPerp} with a perpetual
              {m?.typicalCoins ? ` (a typical training day had ${num(m.typicalCoins, 0)}, ${num(m.typicalWithPerpPct ?? 0, 0)}% with one)` : ""}.
              The number is the percentile: 100 is the best of the day.
            </>
          }
        >
          <div className="grid gap-5 md:grid-cols-2">
            <PickList title="Expected to do best" picks={latest.top} />
            <PickList title="Expected to do worst" picks={[...latest.bottom].reverse()} />
          </div>
          {latest.engine.length > 0 && (
            <div className="mt-4">
              <h3 className="mb-1.5 text-[13px] font-medium text-muted">The engine&apos;s coins</h3>
              <div className="flex flex-wrap gap-2">
                {latest.engine.map((e) => (
                  <Badge
                    key={e.symbol}
                    tone={e.percentile >= 66 ? "good" : e.percentile <= 33 ? "bad" : "neutral"}
                    title={e.percentile >= 66 ? "Ranked in the top third" : e.percentile <= 33 ? "Ranked in the bottom third" : "Ranked in the middle third"}
                  >
                    {coinName(e.symbol)} · {num(e.percentile, 0)}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </Section>
      )}

      {sh.history.length > 0 && (
        <Section
          title="Weeks scored"
          hint="How well each week's ranking matched what really happened. Top and bottom tenth: the average return of the coins ranked best and worst."
          help="Rank-IC: how well the ranking's order matched the order of the realised seven-day returns (1 perfect, 0 no relation)."
        >
          <List>
            {sh.history.map((w) => (
              <Row
                key={w.dayMs}
                label={`Ranked on ${fmtDate(w.dayMs)}`}
                sub={
                  <span className="tabular">
                    Top tenth {num(w.topPct, 1)}%, bottom tenth {num(w.bottomPct, 1)}%, {plural(w.coins, "coin")}
                  </span>
                }
                value={signedNum(w.rankIc)}
                tone={w.rankIc > 0 ? "up" : "down"}
                valueSub={w.rankIc > 0 ? "right way round" : "wrong way round"}
              />
            ))}
          </List>
        </Section>
      )}

      {p.drift.length > 0 && (
        <Section title="M2 inputs against the training data" hint="Whether this week's coins look like what the model learned from.">
          {drifted.length > 0 ? (
            <Notice tone="warning">
              {drifted.length} of {p.drift.length} raw inputs had more than 5% of this week&apos;s coins outside the range the model
              was trained on. The model sees ranks, so it still orders the coins, but on a market it has not seen.
            </Notice>
          ) : (
            <p className="text-[15px] text-ink">All raw inputs of the latest ranking sit inside what the model was trained on.</p>
          )}
          <div className="mt-2">
            <More title={`All ${plural(p.drift.length, "input")}`}>
              <DriftRows drift={p.drift} />
            </More>
          </div>
        </Section>
      )}

      {notes.length > 0 && (
        <Section title="Where the engine sees less than the lab" hint="Gaps between the engine's live data and the lab's.">
          <List>
            {notes.map((n) => (
              <p key={n} className="py-3 text-[15px] leading-relaxed text-ink">
                {n}
              </p>
            ))}
          </List>
        </Section>
      )}
    </>
  );
}
