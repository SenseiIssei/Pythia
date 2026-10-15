import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { BookOpen, ChevronDown, ExternalLink, RefreshCw } from "lucide-react";
import { Button, Card, Chip, Notice, Page, SectionTitle, type ChipTone } from "../design";
import { LoadingRows, Nothing } from "../pagekit";
import { InsightList } from "../components/Insights";
import { Markdown } from "../components/Markdown";
import { liveMode } from "../live";
import { forwardStatus, labStatus, signedPct, type LabStatus, type LearnDigest } from "../lab";
import { ago, feedTone, labFeeds, labStudies, pickInsights, type LabFeed } from "../labFeeds";
import { mlStatus, type MlStatus } from "../ml";
import {
  autopilotLine,
  buildBooks,
  buildStudies,
  gateLine,
  mergeDocs,
  verdictBadge,
  type BookView,
  type StudyView,
} from "../researchView";
import { studyLink } from "../markdown";
import { bundledStudies, labReadme } from "../studyFiles";
import { useAdvanced } from "../uiMode";

/**
 * Everything the research lab knows, in plain words: the strategies being
 * tested and how they are doing, the models and their scores, what the
 * learning loop changed, every lab feed, and every study with its verdict
 * and full write-up. Read-only. Built on the design system (src/design).
 */
export function Research() {
  const engine = liveMode() !== "none";
  const advanced = useAdvanced();
  const [status, setStatus] = useState<LabStatus | null>(null);
  const [feeds, setFeeds] = useState<LabFeed[] | null>(null);
  const [ml, setMl] = useState<MlStatus | null>(null);
  const [docs, setDocs] = useState<Record<string, string> | null>(null);
  const [readme, setReadme] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(engine);
  const [open, setOpen] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(async () => {
    setNow(Date.now());
    const [bundled, rm] = await Promise.all([bundledStudies().catch(() => ({})), labReadme().catch(() => "")]);
    setReadme(rm);
    if (!engine) {
      setDocs(bundled);
      return;
    }
    setLoading(true);
    const [s, f, m, served] = await Promise.allSettled([labStatus(), labFeeds(), mlStatus(), labStudies()]);
    setStatus(s.status === "fulfilled" ? s.value : null);
    setFeeds(f.status === "fulfilled" ? f.value : []);
    setMl(m.status === "fulfilled" ? m.value : null);
    setDocs(mergeDocs(bundled, served.status === "fulfilled" ? served.value : []));
    const failed = [s, f].find((r) => r.status === "rejected") as PromiseRejectedResult | undefined;
    setErr(failed ? String(failed.reason instanceof Error ? failed.reason.message : failed.reason) : "");
    setLoading(false);
  }, [engine]);

  useEffect(() => {
    void load();
  }, [load]);

  const studies = useMemo(() => (docs ? buildStudies(readme, docs) : []), [readme, docs]);
  const books = useMemo(() => buildBooks(status?.forward ?? null, status?.books ?? []), [status]);
  const insights = useMemo(
    () => (feeds ? pickInsights(feeds, status?.forward ?? null, status?.learn ?? null, now) : []),
    [feeds, status, now],
  );

  /** Open a study's write-up and bring it into view. */
  const showStudy = useCallback(
    (name: string) => {
      const target = studies.find((s) => s.file === name || s.id === name);
      if (!target) return;
      setOpen(target.id);
      window.setTimeout(() => document.getElementById(`study-${target.id}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    },
    [studies],
  );

  const otherFeeds = (feeds ?? []).filter((f) => f.name !== "forward" && f.name !== "learn");
  const tested = books.filter((b) => b.forward || b.paper);
  const waiting = books.filter((b) => !b.forward && !b.paper);

  return (
    <Page
      title="Research"
      subtitle="What the lab tried, what it is testing now and what it learned. Numbers are out of sample and after fees."
      right={
        <Button variant="secondary" icon={RefreshCw} onClick={() => void load()}>
          Refresh
        </Button>
      }
    >
      {!engine && (
        <Notice tone="info">
          The forward tests, models and lab feeds are read by the engine, so they need the desktop app or a connected server.
          The studies below ship with the app.
        </Notice>
      )}
      {err && (
        <Notice tone="warning" title="Part of the lab could not be read">
          <span className="break-words">{err}</span>
        </Notice>
      )}

      {engine && (
        <>
          <SectionTitle>Today</SectionTitle>
          <Card>
            {feeds === null ? (
              <Skeletons />
            ) : insights.length === 0 ? (
              <p className="text-muted text-[15px]">All quiet. Nothing in the lab needs your attention today.</p>
            ) : (
              <InsightList insights={insights} now={now} />
            )}
          </Card>
        </>
      )}

      <SectionTitle>Strategies being tested</SectionTitle>
      <p className="text-muted -mt-2 px-1 text-sm">
        Each one first made money in a backtest. Now it trades real prices with play money, to see whether the backtest
        holds.
        {status?.forward?.verdict ? ` ${status.forward.verdict}` : ""}
      </p>
      {loading && !status ? (
        <Card>
          <Skeletons />
        </Card>
      ) : (
        <>
          {tested.map((b) => (
            <BookCard key={b.name} b={b} advanced={advanced} hasStudy={!!(b.info?.study && docs?.[b.info.study])} onStudy={showStudy} />
          ))}
          {waiting.length > 0 && (
            <Card>
              <div className="text-[15px] font-semibold">{tested.length ? "Not on paper right now" : "The lab's strategy books"}</div>
              <p className="text-muted mt-0.5 text-sm">
                {engine ? "No forward test of these is running." : "Their forward tests show with the desktop app or a connected server."}
              </p>
              <div className="mt-1">
                {waiting.map((b) => (
                  <WaitingBook key={b.name} b={b} advanced={advanced} hasStudy={!!(b.info?.study && docs?.[b.info.study])} onStudy={showStudy} />
                ))}
              </div>
            </Card>
          )}
        </>
      )}

      {engine && (
        <>
          <SectionTitle>Models</SectionTitle>
          <ModelScores ml={ml} learn={status?.learn ?? null} />
        </>
      )}

      {engine && status?.learn && (
        <>
          <SectionTitle right={<span className="text-muted text-xs">{status.learn.generatedMs ? ago(status.learn.generatedMs, now) : status.learn.generated}</span>}>
            Learning loop
          </SectionTitle>
          <LearnCard d={status.learn} />
        </>
      )}

      {engine && otherFeeds.length > 0 && (
        <>
          <SectionTitle>Lab feeds</SectionTitle>
          {otherFeeds.map((f) => (
            <FeedCard key={f.name} f={f} now={now} advanced={advanced} onStudy={showStudy} />
          ))}
        </>
      )}

      <SectionTitle>Studies</SectionTitle>
      <p className="text-muted -mt-2 px-1 text-sm">
        Every question the lab asked and what it found. Most ideas fail; a failure with a number is still a result.
      </p>
      {docs === null ? (
        <Card>
          <Skeletons />
        </Card>
      ) : studies.length === 0 ? (
        <Card>
          <Nothing icon={BookOpen} title="No studies found">
            Study write-ups appear here once the lab has published one. Try Refresh.
          </Nothing>
        </Card>
      ) : (
        <>
          <StudyList studies={studies.filter((s) => s.group === "study")} docs={docs} open={open} setOpen={setOpen} onStudy={showStudy} advanced={advanced} />
          {studies.some((s) => s.group === "sweep") && (
            <>
              <SectionTitle>The strategy-family sweep</SectionTitle>
              <p className="text-muted -mt-2 px-1 text-sm">
                Nine families of strategies, 100 variants, judged together so the best of many tries is not mistaken for
                skill.
              </p>
              <StudyList studies={studies.filter((s) => s.group === "sweep")} docs={docs} open={open} setOpen={setOpen} onStudy={showStudy} advanced={advanced} />
            </>
          )}
        </>
      )}
    </Page>
  );
}

/** The shared loading rows, so Research loads like every other page. */
function Skeletons() {
  return <LoadingRows label="Loading the lab" />;
}

const CHIP: Record<string, ChipTone> = { green: "good", amber: "warn", red: "bad", cyan: "good", neutral: "neutral", purple: "neutral" };
const DOT: Record<string, string> = { green: "var(--color-up)", amber: "var(--color-warn)", red: "var(--color-down)", neutral: "var(--color-muted)" };

function Dot({ tone, label }: { tone: string; label: string }) {
  return <span aria-label={label} className="mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: DOT[tone] ?? DOT.neutral }} />;
}

function Progress({ pct, label }: { pct: number; label: string }) {
  const v = Math.max(0, Math.min(100, pct));
  return (
    <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(v)} className="bg-surface-2 h-1.5 w-full overflow-hidden rounded-full">
      <div className="h-full rounded-full" style={{ width: `${v}%`, background: v >= 100 ? "var(--color-up)" : "var(--color-text)" }} />
    </div>
  );
}

function Label({ children }: { children: ReactNode }) {
  return <div className="text-muted mb-1 text-xs font-medium">{children}</div>;
}

function Rows({ rows }: { rows: { k: string; v: string }[] }) {
  return (
    <dl className="space-y-1 text-sm">
      {rows.map((r) => (
        <div key={r.k} className="flex justify-between gap-3">
          <dt className="text-muted">{r.k}</dt>
          <dd className="tabular shrink-0 font-semibold">{r.v}</dd>
        </div>
      ))}
    </dl>
  );
}

function BookCard({ b, advanced, hasStudy, onStudy }: { b: BookView; advanced: boolean; hasStudy: boolean; onStudy: (name: string) => void }) {
  const f = b.forward;
  const st = f ? forwardStatus(f.status) : null;
  const gate = gateLine(b);
  const ret = f?.returnPct ?? b.paper?.returnPct ?? null;
  return (
    <Card label={b.title}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[17px] font-semibold leading-snug">{b.title}</div>
          {advanced && <div className="text-muted text-xs">{b.name}</div>}
        </div>
        {st && <Chip tone={CHIP[st.tone]}>{st.label}</Chip>}
      </div>

      <div className="mt-3 flex items-end justify-between gap-3">
        <div>
          <div className="text-muted text-sm">On paper so far</div>
          <div className={`tabular text-[28px] font-bold leading-tight tracking-tight ${ret == null ? "" : ret >= 0 ? "text-up" : "text-down"}`}>{signedPct(ret)}</div>
        </div>
        {f?.expected && (
          <div className="text-muted text-right text-sm">
            expected
            <div className="tabular font-semibold text-ink">
              {signedPct(f.expected.lowPct, 1)} to {signedPct(f.expected.highPct, 1)}
            </div>
          </div>
        )}
      </div>
      {f?.sentence && <p className="mt-2 text-[15px]">{f.sentence}</p>}
      {b.info && <p className="text-muted mt-2 text-sm">{b.info.what}</p>}

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div className="min-w-0">
          <Label>Backtest</Label>
          {b.info && b.info.backtest.length > 0 ? (
            <Rows rows={b.info.backtest.map((x) => ({ k: x.label, v: x.value }))} />
          ) : (
            <p className="text-muted text-sm">No backtest numbers on file.</p>
          )}
        </div>
        <div className="min-w-0">
          <Label>Checks</Label>
          <Progress pct={gate.pct} label={`${b.title}: paper test progress`} />
          <p className="mt-1.5 text-sm">{gate.text}</p>
          {b.info && <p className="text-muted mt-1 text-xs">{b.info.checks}</p>}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 text-sm">
        <span className={b.autopilots.length ? "font-semibold" : "text-muted"}>{autopilotLine(b)}</span>
        {hasStudy && b.info?.study && (
          <button type="button" onClick={() => onStudy(b.info!.study!)} className="text-sm font-semibold underline underline-offset-2">
            Read the study
          </button>
        )}
      </div>
    </Card>
  );
}

/** A catalogued book with no forward test: what it is and what its backtest said, folded. */
function WaitingBook({ b, advanced, hasStudy, onStudy }: { b: BookView; advanced: boolean; hasStudy: boolean; onStudy: (name: string) => void }) {
  const [open, setOpen] = useState(false);
  const headline = b.info?.backtest[0];
  return (
    <div className="border-t border-line first:border-t-0">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center gap-3 py-3 text-left">
        <span className="min-w-0 flex-1">
          <span className="block text-[15px] font-semibold">{b.title}</span>
          {headline && (
            <span className="text-muted block text-sm">
              {headline.label}: <span className="tabular">{headline.value}</span>
            </span>
          )}
        </span>
        <ChevronDown size={16} aria-hidden className={`text-muted shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && b.info && (
        <div className="space-y-2 pb-3 text-sm">
          {advanced && <div className="text-muted text-xs">{b.name}</div>}
          <p>{b.info.what}</p>
          {b.info.backtest.length > 0 && <Rows rows={b.info.backtest.map((x) => ({ k: x.label, v: x.value }))} />}
          <p className="text-muted text-xs">{b.info.checks}</p>
          <p className="text-muted text-xs">{autopilotLine(b)}</p>
          {hasStudy && b.info.study && (
            <button type="button" onClick={() => onStudy(b.info!.study!)} className="font-semibold underline underline-offset-2">
              Read the study
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function ModelScores({ ml, learn }: { ml: MlStatus | null; learn: LearnDigest | null }) {
  const vol = ml?.model ? ml : null;
  const picks = ml?.picks?.model ? ml.picks : null;
  const pct = (v: number | null | undefined, d = 1) => (v == null || !Number.isFinite(v) ? "n/a" : `${v.toFixed(d)} %`);
  const num = (v: number | null | undefined, d = 3) => (v == null || !Number.isFinite(v) ? "n/a" : v.toFixed(d));
  return (
    <>
      <Card>
        <div className="text-[15px] font-semibold">Next-hour volatility (M1)</div>
        <p className="text-muted mt-0.5 text-sm">How much each coin will move in the next hour. Used to size trades, never to pick them.</p>
        <div className="mt-3">
          {vol ? (
            <Rows
              rows={[
                { k: "Better than the simple model, in the lab", v: pct(vol.model!.labGainVsHarPct) },
                { k: "Better than the simple model, live", v: pct(vol.shadow.gainVsHarPct) },
                { k: "Hours scored live", v: vol.shadow.scored.toLocaleString() },
                { k: "Version", v: vol.model!.version },
              ]}
            />
          ) : (
            <p className="text-muted text-sm">{ml?.message || "No model loaded."}</p>
          )}
        </div>
      </Card>
      <Card>
        <div className="text-[15px] font-semibold">Weekly coin ranking (M2)</div>
        <p className="text-muted mt-0.5 text-sm">Ranks coins by how they should do over the next week, scored a week later.</p>
        <div className="mt-3">
          {picks ? (
            <Rows
              rows={[
                { k: "Ranking skill in the lab (rank-IC)", v: num(picks.model!.labRankIc) },
                { k: "Ranking skill live", v: num(picks.shadow.rankIc) },
                { k: "Weeks scored live", v: String(picks.shadow.weeks) },
                { k: "Version", v: picks.model!.version },
              ]}
            />
          ) : (
            <p className="text-muted text-sm">{ml?.picks?.message || "No model loaded."}</p>
          )}
        </div>
      </Card>
      {learn && learn.decisions.length > 0 && (
        <Card>
          <div className="text-[15px] font-semibold">Last model decisions</div>
          <p className="text-muted mt-0.5 text-sm">A new version replaces the old one only when it is better on data neither has seen.</p>
          <ul className="mt-2">
            {learn.decisions.map((d, i) => (
              <li key={i} className="flex items-start justify-between gap-3 border-t border-line py-2.5 first:border-t-0">
                <div className="min-w-0">
                  <div className="text-[15px] font-semibold">{d.model}</div>
                  {d.why && <div className="text-muted text-sm">{d.why}</div>}
                </div>
                <Chip tone={d.decision === "promoted" ? "good" : d.decision === "rejected" ? "warn" : "neutral"}>
                  {d.decision === "promoted" ? "now in use" : d.decision === "rejected" ? "turned down" : "kept as is"}
                </Chip>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}

function LearnCard({ d }: { d: LearnDigest }) {
  const failed = d.steps.filter((x) => x.status === "failed");
  return (
    <Card>
      <p className="text-[15px]">{d.headline || "Nothing changed."}</p>
      {d.changes.length > 0 && (
        <ul className="mt-2">
          {d.changes.map((c, i) => (
            <li key={i} className="border-t border-line py-2.5 first:border-t-0">
              <div className="flex items-start justify-between gap-3">
                <span className="text-[15px] font-semibold">{c.what}</span>
                <Chip>{c.area}</Chip>
              </div>
              {c.why && <div className="text-muted text-sm">{c.why}</div>}
            </li>
          ))}
        </ul>
      )}
      {failed.map((x) => (
        <p key={x.step} className="text-down mt-2 break-words text-sm">
          Step {x.step} failed: {x.detail}
        </p>
      ))}
      <p className="text-muted mt-2 text-xs">It updates costs, evidence and models within fixed bounds. It cannot arm live trading or move money.</p>
    </Card>
  );
}

function FeedCard({ f, now, advanced, onStudy }: { f: LabFeed; now: number; advanced: boolean; onStudy: (name: string) => void }) {
  const [all, setAll] = useState(false);
  const t = feedTone(f.status);
  const items = all ? f.items : f.items.slice(0, 5);
  return (
    <Card label={f.title}>
      <div className="flex items-start gap-3">
        <Dot tone={t.tone} label={t.label} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3">
            <span className="text-[15px] font-semibold">{f.title}</span>
            <span className="text-muted text-xs">{ago(f.updatedMs, now)}</span>
          </div>
          {f.headline && <p className="text-muted mt-0.5 text-sm">{f.headline}</p>}
          {advanced && !f.conforms && (
            <div className="mt-1">
              <Chip title="This report does not carry the common feed header (docs/LAB-FEEDS.md).">older format</Chip>
            </div>
          )}
        </div>
      </div>
      {items.length > 0 && (
        <ul className="mt-2">
          {items.map((it, i) => {
            const study = it.link ? studyLink(it.link) : null;
            const web = it.link && /^https?:\/\//.test(it.link) ? it.link : null;
            const label = study ? (
              <button type="button" onClick={() => onStudy(study)} className="text-left underline underline-offset-2">
                {it.label}
              </button>
            ) : web ? (
              <a href={web} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 underline underline-offset-2">
                {it.label}
                <ExternalLink size={12} aria-hidden />
              </a>
            ) : (
              it.label
            );
            return (
              <li key={i} className="flex items-start justify-between gap-3 border-t border-line py-2.5">
                <div className="min-w-0">
                  <div className="text-[15px] font-medium">{label}</div>
                  {it.detail && <div className="text-muted text-sm">{it.detail}</div>}
                </div>
                {it.value && (
                  <span className={`tabular shrink-0 text-[15px] font-semibold ${it.status === "bad" ? "text-down" : it.status === "watch" ? "text-warn" : ""}`}>{it.value}</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {f.items.length > 5 && (
        <button type="button" onClick={() => setAll((a) => !a)} className="mt-1 text-sm font-semibold underline underline-offset-2">
          {all ? "Show fewer" : `Show all ${f.items.length}`}
        </button>
      )}
    </Card>
  );
}

function StudyList({
  studies,
  docs,
  open,
  setOpen,
  onStudy,
  advanced,
}: {
  studies: StudyView[];
  docs: Record<string, string>;
  open: string | null;
  setOpen: (id: string | null) => void;
  onStudy: (name: string) => void;
  advanced: boolean;
}) {
  return (
    <Card className="!p-0">
      {studies.map((s, i) => {
        const isOpen = open === s.id;
        const v = verdictBadge(s.kind);
        const md = s.file ? docs[s.file] : undefined;
        return (
          <div key={s.id} id={`study-${s.id}`} className={`scroll-mt-4 ${i > 0 ? "border-t border-line" : ""}`}>
            <button
              type="button"
              onClick={() => setOpen(isOpen ? null : s.id)}
              aria-expanded={isOpen}
              className="flex w-full items-start gap-3 rounded-2xl px-4 py-3.5 text-left"
            >
              <div className="min-w-0 flex-1">
                <div className="text-[15px] font-semibold leading-snug">{s.title}</div>
                <p className="text-muted mt-1 text-sm">{s.verdict}</p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Chip tone={CHIP[v.tone]}>{v.label}</Chip>
                  <span className="text-muted text-xs">
                    {s.date ?? "undated"}
                    {advanced && ` · ${s.code}`}
                  </span>
                </div>
              </div>
              <ChevronDown size={18} aria-hidden className={`text-muted mt-0.5 shrink-0 transition-transform ${isOpen ? "rotate-180" : ""}`} />
            </button>
            {isOpen && (
              <div className="px-4 pb-5">
                {md ? (
                  <Markdown source={md} onStudy={onStudy} />
                ) : (
                  <p className="text-muted text-sm">There is no separate write-up for this one; the answer above is the lab's summary of it.</p>
                )}
              </div>
            )}
          </div>
        );
      })}
    </Card>
  );
}
