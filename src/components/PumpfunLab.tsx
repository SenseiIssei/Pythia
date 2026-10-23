// The Lab page's pump.fun section: the real-time study's verdict, the measured
// execution of the live orders, every pipeline strategy with its readiness,
// shadow book and paper book of the last seven days (a small chart each), and
// the newest pump.fun studies with their verdict lines. Paper only, read only.

import { Badge, Chip, List, Notice, Sparkline, type ChipTone } from "../design";
import { More, Row, Section, plural } from "../pagekit";
import { feedTone, ago } from "../labFeeds";
import { verdictBadge, type StudyView } from "../researchView";
import { sharePct, strategyRows, type PumpfunBook, type PumpfunLab as Lab, type StrategyRow } from "../pumpfunLab";
import { sol } from "../pumpfunLive";

const FEED_CHIP: Record<string, ChipTone> = { green: "good", amber: "warn", red: "bad", neutral: "neutral" };
const VERDICT_CHIP: Record<string, ChipTone> = { green: "good", amber: "warn", neutral: "neutral" };

const toneText = (v: number | null | undefined) => (v == null || v === 0 ? "text-ink" : v > 0 ? "text-up" : "text-down");
const dayMs = (ms: number) => new Date(ms).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function BookDetail({ b }: { b: PumpfunBook }) {
  return (
    <More title={`Last ${plural(b.days.length, "day")}, newest first`}>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-left text-faint">
              <th className="py-1 pr-3 font-medium">Day</th>
              <th className="py-1 pr-3 text-right font-medium">Entries</th>
              <th className="py-1 pr-3 text-right font-medium">Mean</th>
              <th className="py-1 text-right font-medium">P&amp;L</th>
            </tr>
          </thead>
          <tbody className="tabular">
            {b.days.map((d) => (
              <tr key={d.day} className="border-t border-line">
                <td className="py-1 pr-3">{d.day}</td>
                <td className="py-1 pr-3 text-right">{d.entries}</td>
                <td className={`py-1 pr-3 text-right ${toneText(d.mean)}`}>{sharePct(d.mean)}</td>
                <td className={`py-1 text-right ${toneText(d.pnlSol)}`}>{sol(d.pnlSol, true, 3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {b.recent.length > 0 && (
        <ul className="mt-3 divide-y divide-line text-[13px]">
          {b.recent.map((e, i) => (
            <li key={`${e.exitMs}-${i}`} className="flex items-baseline justify-between gap-3 py-1.5">
              <span className="min-w-0 truncate text-muted">
                {dayMs(e.exitMs)} · {e.symbol ?? "?"}
                {e.exitWhy ? ` · ${e.exitWhy}` : ""}
              </span>
              <span className={`tabular shrink-0 ${toneText(e.pnlSol)}`}>
                {sharePct(e.ret)} · {sol(e.pnlSol, true, 3)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </More>
  );
}

function StrategyItem({ r, days }: { r: StrategyRow; days: number }) {
  const b = r.book;
  const rd = r.readiness;
  return (
    <div className="py-3" data-strategy={r.rule}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="min-w-0 truncate font-code text-[14px] font-semibold text-ink">{r.rule}</span>
        <Chip tone={r.ready ? "good" : "neutral"}>{r.ready ? "Ready for live" : "Not ready"}</Chip>
      </div>
      {r.checks.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1" aria-label="Checks before live">
          {r.checks.map((c) => (
            <Badge key={c.label} tone={c.ok ? "good" : "neutral"}>
              {c.ok ? "✓" : "·"} {c.label}
            </Badge>
          ))}
        </div>
      )}
      <div className="mt-2 grid grid-cols-[1fr_auto] items-center gap-3">
        <div className="min-w-0 text-[13px] text-muted">
          {b ? (
            <>
              Paper, last {days} days: <span className="tabular text-ink">{plural(b.entries, "entry", "entries")}</span>, mean{" "}
              <span className={`tabular ${toneText(b.mean)}`}>{sharePct(b.mean)}</span> per entry,{" "}
              <span className={`tabular ${toneText(b.pnlSol)}`}>{sol(b.pnlSol, true, 3)}</span>
            </>
          ) : (
            `No paper entry in the last ${days} days.`
          )}
          {rd && (
            <div>
              Study: {plural(rd.trades ?? 0, "trade")} over {plural(rd.days ?? 0, "day")}, mean {sharePct(rd.mean)}
              {r.shadow ? ` · shadow ${plural(r.shadow.n ?? 0, "entry", "entries")}, ${sharePct(r.shadow.mean)}` : ""}
            </div>
          )}
        </div>
        <div className="w-24 sm:w-32">
          <Sparkline data={b ? b.curve.map((p) => p[1]) : []} height={36} fill label={`${r.rule}: running paper P&L over ${days} days, now ${b ? sol(b.pnlSol, true, 3) : "none"}`} />
        </div>
      </div>
      {b && b.days.length > 0 && <BookDetail b={b} />}
    </div>
  );
}

/** The section itself; the Lab page reads the data and polls it. */
export function PumpfunLab({ lab, studies, err, now }: { lab: Lab | null; studies: StudyView[]; err: string; now: number }) {
  const rows = strategyRows(lab);
  const head = lab ? feedTone(lab.status) : null;
  const ex = lab?.execution;
  return (
    <Section
      title="pump.fun lab"
      hint="The real-time study on paper: which pipeline strategy would be ready for live, the paper books of the last days, and how the live orders really land. Paper only."
      right={head && <Chip tone={FEED_CHIP[head.tone] ?? "neutral"}>{lab?.updatedMs ? ago(lab.updatedMs, now) : head.label}</Chip>}
    >
      {err && !lab && <p className="text-sm text-muted">{err}</p>}
      {lab && !lab.found && <p className="text-sm text-muted">No pump.fun study report in the lab's data folder yet.</p>}
      {lab?.found && (
        <div className="space-y-4">
          {lab.headline && <p className="text-[15px] leading-relaxed text-ink">{lab.headline}</p>}
          {lab.caveat && <Notice tone="warning">{lab.caveat}</Notice>}

          {ex && (ex.fills ?? 0) > 0 && (
            <div>
              <h3 className="text-[13px] font-semibold text-muted">Measured execution</h3>
              {ex.verdict && <p className="mt-1 text-sm leading-relaxed text-ink">{ex.verdict}</p>}
              <div className="mt-1 divide-y divide-line">
                <Row label="Fills" value={String(ex.fills ?? 0)} valueSub={`${ex.failed ?? 0} failed`} />
                <Row label="Buy latency, median" value={ex.lat_buy_ms?.median == null ? "n/a" : `${Math.round(ex.lat_buy_ms.median)} ms`} />
                <Row label="Buy slippage, median" value={sharePct(ex.slip_buy?.median)} sub={ex.paper_slip?.median == null ? undefined : `paper ${sharePct(ex.paper_slip.median)}`} />
              </div>
            </div>
          )}

          <div>
            <h3 className="text-[13px] font-semibold text-muted">
              Pipeline strategies{lab.pick ? ` · study pick ${lab.pick}` : ""}
            </h3>
            {rows.length === 0 ? (
              <p className="mt-1 text-sm text-muted">No pipeline strategy in the report yet.</p>
            ) : (
              <List>
                {rows.map((r) => (
                  <StrategyItem key={r.rule} r={r} days={lab.bookDays || 7} />
                ))}
              </List>
            )}
          </div>
        </div>
      )}

      {studies.length > 0 && (
        <div className="mt-4">
          <h3 className="text-[13px] font-semibold text-muted">Newest pump.fun studies</h3>
          <List>
            {studies.map((s) => {
              const v = verdictBadge(s.kind);
              return (
                <div key={s.id} className="py-3">
                  <div className="flex items-start justify-between gap-3">
                    <span className="min-w-0 text-[15px] font-semibold text-ink">{s.title}</span>
                    <Chip tone={VERDICT_CHIP[v.tone] ?? "neutral"}>{v.label}</Chip>
                  </div>
                  <p className="mt-0.5 text-[13px] leading-relaxed text-muted">{s.verdict}</p>
                  <p className="mt-0.5 text-[12px] text-faint">
                    {s.file ? `results/${s.file}.md` : s.code}
                    {s.date ? ` · ${s.date}` : ""}
                  </p>
                </div>
              );
            })}
          </List>
        </div>
      )}
    </Section>
  );
}
