// M2 "Picks" on the Models page: the weekly coin ranking in shadow mode.
// Read-only apart from "Rank now", which only asks the engine to rank and record.

import { useState } from "react";
import { Activity, ListOrdered, Play, Target, TriangleAlert, Trophy } from "lucide-react";
import { Badge, Button, Card, StatCard } from "./ui";
import { runPicks, type DriftLevel, type PickView, type PicksStatus } from "../ml";

const NONE = "not yet";
const fmtDate = (ms: number) => new Date(ms).toLocaleDateString();
const fmtIc = (v: number | null | undefined) => (v === null || v === undefined ? NONE : v.toFixed(3));
const coin = (s: string) => s.replace(/USDT$/, "");

const DRIFT_TONE: Record<DriftLevel, "green" | "purple" | "red"> = { stable: "green", shift: "purple", drift: "red" };
const DRIFT_WORD: Record<DriftLevel, string> = {
  stable: "like training",
  shift: "different regime",
  drift: "outside trained range",
};

function PickList({ title, picks, tone }: { title: string; picks: PickView[]; tone: "green" | "red" }) {
  return (
    <div>
      <div className="mb-1.5 text-xs uppercase tracking-wide text-cyber-text-faint">{title}</div>
      <ol className="space-y-1 text-sm tabular-nums">
        {picks.map((p) => (
          <li key={p.symbol} className="flex items-center justify-between border-t border-cyber-border py-1">
            <span className="text-cyber-text">
              <span className="mr-2 text-cyber-text-faint">{p.rank}.</span>
              {coin(p.symbol)}
              {!p.perp && <span className="ml-2 text-[11px] text-cyber-text-faint">no perp</span>}
            </span>
            <span className={tone === "green" ? "text-success" : "text-danger"}>{p.percentile.toFixed(0)}</span>
          </li>
        ))}
      </ol>
    </div>
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
      <Card
        title="Weekly coin ranking (M2)"
        right={
          <div className="flex items-center gap-2">
            <Badge tone="purple">shadow mode</Badge>
            {m && (
              <Button tone="neutral" icon={Play} onClick={() => void rankNow()} disabled={p.running}>
                {p.running ? "Running" : "Rank now"}
              </Button>
            )}
          </div>
        }
      >
        <p className="text-sm text-cyber-text-dim">
          Ranks every liquid Binance coin by how it is likely to do over the next seven days compared with the others.
          It says which coins should beat or lag the rest, not whether the market as a whole goes up.
        </p>
        {m && (
          <p className="mt-2 text-sm text-cyber-text-dim">
            Version {m.version}, {m.trees} trees, trained on data up to {fmtDate(m.trainToMs)}. In the lab its ranking
            agreed with the following week by a Rank-IC of <span className="text-accent">{fmtIc(lab)}</span> out of
            sample{m.labRankIcLiquid50 !== null && <> ({m.labRankIcLiquid50.toFixed(3)} among the 50 most liquid coins)</>}.
            It is ranked once a week and scored when that week is over; nothing is traded on it.
          </p>
        )}
        {p.state !== "live" && (
          <div className="mt-3 flex items-start gap-3 text-sm">
            <TriangleAlert size={18} className={`mt-0.5 shrink-0 ${p.state === "rejected" ? "text-danger" : "text-warning"}`} />
            <div>
              <div className="font-bold text-cyber-text">
                {p.state === "rejected" ? "Model refused" : p.state === "warmingUp" ? "Warming up" : "No model"}
              </div>
              <div className="text-cyber-text-dim">{p.message}</div>
            </div>
          </div>
        )}
        {p.state === "live" && <p className="mt-2 text-xs text-cyber-text-faint">{p.message}</p>}
        {asked && !p.running && <p className="mt-1 text-xs text-cyber-text-faint">Asked for a ranking; it takes a few minutes.</p>}
        {err && <p className="mt-1 text-xs text-danger">{err}</p>}
      </Card>

      {m && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard
            label="Weeks scored live"
            value={sh.weeks}
            icon={Activity}
            sub={sh.sinceMs ? `since ${fmtDate(sh.sinceMs)}` : "first score a week after the first ranking"}
          />
          <StatCard
            label="Live Rank-IC"
            value={fmtIc(live)}
            icon={Trophy}
            tone={live === null ? "cyan" : lab !== null && live >= lab * 0.5 ? "green" : live > 0 ? "purple" : "red"}
            sub={lab === null ? "" : `backtest ${lab.toFixed(3)}`}
          />
          <StatCard
            label="Last 8 weeks"
            value={fmtIc(sh.rankIcRecent)}
            icon={Target}
            sub={sh.rankIcT === null ? "t-statistic after three weeks" : `t ${sh.rankIcT.toFixed(1)} over all weeks`}
          />
          <StatCard
            label="Weeks right"
            value={sh.hitRate === null ? NONE : `${(sh.hitRate * 100).toFixed(0)} %`}
            icon={ListOrdered}
            sub="weeks with a positive Rank-IC"
          />
        </div>
      )}

      {latest && (
        <Card title={`Ranking of ${fmtDate(latest.dayMs)}, for the week after`}>
          <p className="mb-3 text-sm text-cyber-text-dim">
            {latest.coins} coins ranked, {latest.withPerp} with a perpetual
            {m?.typicalCoins ? ` (a typical training day had ${m.typicalCoins.toFixed(0)}, ${m.typicalWithPerpPct?.toFixed(0)} % with one)` : ""}.
            The number is the percentile: 100 is the best of the day.
          </p>
          <div className="grid gap-4 md:grid-cols-2">
            <PickList title="Expected to do best" picks={latest.top} tone="green" />
            <PickList title="Expected to do worst" picks={[...latest.bottom].reverse()} tone="red" />
          </div>
          {latest.engine.length > 0 && (
            <div className="mt-4">
              <div className="mb-1.5 text-xs uppercase tracking-wide text-cyber-text-faint">The engine&apos;s coins</div>
              <div className="flex flex-wrap gap-2">
                {latest.engine.map((e) => (
                  <Badge key={e.symbol} tone={e.percentile >= 66 ? "green" : e.percentile <= 33 ? "red" : "neutral"}>
                    {coin(e.symbol)} · {e.percentile.toFixed(0)}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </Card>
      )}

      {sh.history.length > 0 && (
        <Card title="Weeks scored">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-cyber-text-faint">
                  <th className="py-1.5 pr-3">Ranked on</th>
                  <th className="py-1.5 pr-3 text-right">Rank-IC</th>
                  <th className="py-1.5 pr-3 text-right">Top tenth</th>
                  <th className="py-1.5 pr-3 text-right">Bottom tenth</th>
                  <th className="py-1.5 text-right">Coins</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {sh.history.map((w) => (
                  <tr key={w.dayMs} className="border-t border-cyber-border">
                    <td className="py-1.5 pr-3 text-cyber-text">{fmtDate(w.dayMs)}</td>
                    <td className={`py-1.5 pr-3 text-right ${w.rankIc > 0 ? "text-success" : "text-danger"}`}>{w.rankIc.toFixed(3)}</td>
                    <td className="py-1.5 pr-3 text-right text-cyber-text-dim">{w.topPct.toFixed(1)} %</td>
                    <td className="py-1.5 pr-3 text-right text-cyber-text-dim">{w.bottomPct.toFixed(1)} %</td>
                    <td className="py-1.5 text-right text-cyber-text-dim">{w.coins}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-cyber-text-faint">
            Rank-IC: how well the ranking&apos;s order matched the order of the realised seven-day returns (1 perfect, 0
            no relation). Top and bottom tenth: the average realised return of the coins ranked best and worst.
          </p>
        </Card>
      )}

      {p.drift.length > 0 && (
        <Card title="M2 inputs against the training data">
          {drifted.length > 0 ? (
            <p className="mb-3 text-sm text-danger">
              {drifted.length} of {p.drift.length} raw inputs had more than 5 % of this week&apos;s coins outside the range
              the model was trained on. The model sees ranks, so it still orders the coins, but on a market it has not seen.
            </p>
          ) : (
            <p className="mb-3 text-sm text-cyber-text-dim">
              All raw inputs of the latest ranking sit inside what the model was trained on.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {p.drift.map((d) => (
              <span key={d.feature} title={`${d.outsidePct.toFixed(1)} % outside the trained range, PSI ${d.psi.toFixed(2)}`}>
                <Badge tone={DRIFT_TONE[d.level]}>
                  {d.feature} · {DRIFT_WORD[d.level]}
                </Badge>
              </span>
            ))}
          </div>
        </Card>
      )}

      {notes.length > 0 && (
        <Card title="Where the engine sees less than the lab">
          <ul className="list-disc space-y-1 pl-5 text-sm text-cyber-text-dim">
            {notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
