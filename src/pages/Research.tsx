import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { BookOpen, ChevronDown, ExternalLink, RefreshCw } from "lucide-react";
import { Badge, Button, Card, EmptyState, Loading, Meter, Notice, PageHeader, Term } from "../components/ui";
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
 * and full write-up. Read-only.
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
    const [s, f, m, served] = await Promise.allSettled([labStatus(), labFeeds(), mlStatus(), labStudies()]);
    setStatus(s.status === "fulfilled" ? s.value : null);
    setFeeds(f.status === "fulfilled" ? f.value : []);
    setMl(m.status === "fulfilled" ? m.value : null);
    setDocs(mergeDocs(bundled, served.status === "fulfilled" ? served.value : []));
    const failed = [s, f].find((r) => r.status === "rejected") as PromiseRejectedResult | undefined;
    setErr(failed ? String(failed.reason instanceof Error ? failed.reason.message : failed.reason) : "");
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

  return (
    <div className="animate-fade-in mx-auto max-w-4xl space-y-5">
      <PageHeader
        title="Research"
        subtitle="What the lab has tried, what is being tested now and what it learned. Every number is out of sample and after fees unless it says otherwise."
        right={
          <Button tone="neutral" size="sm" icon={RefreshCw} onClick={() => void load()}>
            Refresh
          </Button>
        }
      />

      {!engine && (
        <Notice tone="info" title="Studies only">
          The forward tests, models and lab feeds are read by the engine, so they need the desktop app or a connected
          server. The studies below ship with the app.
        </Notice>
      )}
      {err && (
        <Notice tone="warning" title="Part of the lab could not be read">
          {err}
        </Notice>
      )}

      {engine && (
        <Section title="Today" subtitle="The few things from the lab worth knowing right now.">
          <Card>
            {feeds === null ? (
              <Loading>Reading the lab</Loading>
            ) : insights.length === 0 ? (
              <p className="text-sm text-cyber-text-dim">All quiet. Nothing in the lab needs your attention today.</p>
            ) : (
              <InsightList insights={insights} now={now} />
            )}
          </Card>
        </Section>
      )}

      <Section
        title="Strategies being tested"
        subtitle="Each one first had to make money in a backtest. Now it trades real prices with play money, to see whether the backtest holds."
      >
        {engine && !status && !err ? (
          <Loading>Reading the forward tests</Loading>
        ) : (
          <div className="space-y-3">
            {status?.forward?.verdict && <p className="text-sm text-cyber-text-dim">{status.forward.verdict}</p>}
            {books.map((b) => (
              <BookCard key={b.name} b={b} advanced={advanced} hasStudy={!!(b.info?.study && docs?.[b.info.study])} onStudy={showStudy} />
            ))}
          </div>
        )}
      </Section>

      {engine && (
        <Section title="Models" subtitle="The models score themselves on what happened after each forecast, not on the data they learned from.">
          <ModelScores ml={ml} learn={status?.learn ?? null} />
        </Section>
      )}

      {engine && status?.learn && (
        <Section title="What the learning loop changed" subtitle="Every night it updates costs, evidence and models within fixed bounds. It cannot arm live trading or move money.">
          <LearnCard d={status.learn} now={now} />
        </Section>
      )}

      {engine && otherFeeds.length > 0 && (
        <Section title="Lab feeds" subtitle="Every other lab job that reports here, worst first.">
          <div className="space-y-3">
            {otherFeeds.map((f) => (
              <FeedCard key={f.name} f={f} now={now} advanced={advanced} onStudy={showStudy} />
            ))}
          </div>
        </Section>
      )}

      <Section
        title="Studies"
        subtitle="Every question the lab asked, with its answer. Most ideas fail; a failure with a number is still a result. Open one for the full write-up."
      >
        {docs === null ? (
          <Loading>Loading the write-ups</Loading>
        ) : studies.length === 0 ? (
          <Card>
            <EmptyState icon={BookOpen} title="No studies found" compact />
          </Card>
        ) : (
          <div className="space-y-4">
            <StudyList
              studies={studies.filter((s) => s.group === "study")}
              docs={docs}
              open={open}
              setOpen={setOpen}
              onStudy={showStudy}
              advanced={advanced}
            />
            {studies.some((s) => s.group === "sweep") && (
              <div>
                <h3 className="mb-2 text-sm font-medium text-cyber-text">The strategy-family sweep</h3>
                <p className="mb-2 text-xs leading-relaxed text-cyber-text-faint">
                  Nine families of strategies, 100 variants, all judged together so the best of many tries is not
                  mistaken for skill.
                </p>
                <StudyList
                  studies={studies.filter((s) => s.group === "sweep")}
                  docs={docs}
                  open={open}
                  setOpen={setOpen}
                  onStudy={showStudy}
                  advanced={advanced}
                />
              </div>
            )}
          </div>
        )}
      </Section>
    </div>
  );
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <section className="space-y-2.5">
      <div>
        <h2 className="text-base font-semibold text-cyber-text">{title}</h2>
        {subtitle && <p className="mt-0.5 max-w-2xl text-sm leading-relaxed text-cyber-text-dim">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

function Label({ children }: { children: ReactNode }) {
  return <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-cyber-text-faint">{children}</div>;
}

function BookCard({
  b,
  advanced,
  hasStudy,
  onStudy,
}: {
  b: BookView;
  advanced: boolean;
  hasStudy: boolean;
  onStudy: (name: string) => void;
}) {
  const f = b.forward;
  const st = f ? forwardStatus(f.status) : null;
  const gate = gateLine(b);
  const ret = f?.returnPct ?? b.paper?.returnPct ?? null;
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-0">
          <div className="text-[15px] font-semibold text-cyber-text">{b.title}</div>
          {advanced && <div className="text-xs text-cyber-text-faint">{b.name}</div>}
        </div>
        {st ? <Badge tone={st.tone}>{st.label}</Badge> : <Badge tone="neutral">not on paper</Badge>}
      </div>
      {b.info && <p className="mt-1.5 text-sm leading-relaxed text-cyber-text-dim">{b.info.what}</p>}

      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <div className="min-w-0">
          <Label>
            <Term k="Backtest">Backtest</Term>
          </Label>
          {b.info && b.info.backtest.length > 0 ? (
            <dl className="space-y-1 text-sm">
              {b.info.backtest.map((x) => (
                <div key={x.label} className="flex justify-between gap-2">
                  <dt className="text-cyber-text-dim">{x.label}</dt>
                  <dd className="font-mono tabular-nums text-cyber-text">{x.value}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-sm text-cyber-text-faint">No backtest numbers on file.</p>
          )}
        </div>
        <div className="min-w-0">
          <Label>Forward test so far</Label>
          {ret != null ? (
            <>
              <div className={`font-mono text-xl font-semibold tabular-nums ${ret >= 0 ? "text-success" : "text-danger"}`}>{signedPct(ret)}</div>
              {f?.expected && (
                <div className="text-xs text-cyber-text-faint">
                  expected {signedPct(f.expected.lowPct)} to {signedPct(f.expected.highPct)} after {Math.round(f.days)} days
                </div>
              )}
              {f?.sentence && <p className="mt-1 text-sm leading-relaxed text-cyber-text-dim">{f.sentence}</p>}
            </>
          ) : (
            <p className="text-sm text-cyber-text-faint">No forward test yet.</p>
          )}
        </div>
        <div className="min-w-0">
          <Label>
            <Term k="Gate 7">Checks</Term>
          </Label>
          <Meter pct={gate.pct} tone={gate.ready ? "green" : "neutral"} label={`${b.title}: paper test progress`} />
          <p className="mt-1.5 text-sm leading-relaxed text-cyber-text-dim">{gate.text}</p>
          {b.info && <p className="mt-1 text-xs leading-relaxed text-cyber-text-faint">{b.info.checks}</p>}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-cyber-border pt-3 text-sm">
        <span className={b.autopilots.length ? "text-accent" : "text-cyber-text-dim"}>{autopilotLine(b)}</span>
        {hasStudy && b.info?.study && (
          <button type="button" onClick={() => onStudy(b.info!.study!)} className="text-xs font-medium text-accent hover:underline">
            Read the study
          </button>
        )}
      </div>
    </Card>
  );
}

function ModelScores({ ml, learn }: { ml: MlStatus | null; learn: LearnDigest | null }) {
  const vol = ml?.model ? ml : null;
  const picks = ml?.picks?.model ? ml.picks : null;
  const pct = (v: number | null | undefined, d = 1) => (v == null || !Number.isFinite(v) ? "n/a" : `${v.toFixed(d)} %`);
  const num = (v: number | null | undefined, d = 3) => (v == null || !Number.isFinite(v) ? "n/a" : v.toFixed(d));
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Card>
          <div className="text-[15px] font-semibold text-cyber-text">Next-hour volatility (M1)</div>
          <p className="mt-1 text-sm text-cyber-text-dim">How much each coin will move in the next hour. Used to size trades, never to pick them.</p>
          {vol ? (
            <dl className="mt-3 space-y-1 text-sm">
              <Score k="Better than the simple model, in the lab" v={pct(vol.model!.labGainVsHarPct)} />
              <Score k="Better than the simple model, live" v={pct(vol.shadow.gainVsHarPct)} />
              <Score k="Hours scored live" v={vol.shadow.scored.toLocaleString()} />
              <Score k="Version" v={vol.model!.version} />
            </dl>
          ) : (
            <p className="mt-3 text-sm text-cyber-text-faint">{ml?.message || "No model loaded."}</p>
          )}
        </Card>
        <Card>
          <div className="text-[15px] font-semibold text-cyber-text">Weekly coin ranking (M2)</div>
          <p className="mt-1 text-sm text-cyber-text-dim">Ranks coins by how they should do over the next week. Scored a week later.</p>
          {picks ? (
            <dl className="mt-3 space-y-1 text-sm">
              <Score k="Ranking skill in the lab (rank-IC)" v={num(picks.model!.labRankIc)} />
              <Score k="Ranking skill live" v={num(picks.shadow.rankIc)} />
              <Score k="Weeks scored live" v={String(picks.shadow.weeks)} />
              <Score k="Version" v={picks.model!.version} />
            </dl>
          ) : (
            <p className="mt-3 text-sm text-cyber-text-faint">{ml?.picks?.message || "No model loaded."}</p>
          )}
        </Card>
      </div>
      {learn && learn.decisions.length > 0 && (
        <Card>
          <Label>Last model decisions</Label>
          <ul className="space-y-2">
            {learn.decisions.map((d, i) => (
              <li key={i} className="text-sm">
                <span className="text-cyber-text">{d.model}</span>{" "}
                <Badge tone={d.decision === "promoted" ? "green" : d.decision === "rejected" ? "amber" : "neutral"}>
                  {d.decision === "promoted" ? "new version in use" : d.decision === "rejected" ? "turned down" : "kept as is"}
                </Badge>
                {d.why && <div className="mt-0.5 text-cyber-text-dim">{d.why}</div>}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-cyber-text-faint">A new version replaces the old one only when it is better on data neither has seen.</p>
        </Card>
      )}
    </div>
  );
}

function Score({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-cyber-text-dim">{k}</dt>
      <dd className="shrink-0 font-mono tabular-nums text-cyber-text">{v}</dd>
    </div>
  );
}

function LearnCard({ d, now }: { d: LearnDigest; now: number }) {
  const failed = d.steps.filter((x) => x.status === "failed");
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="min-w-0 flex-1 text-sm leading-relaxed text-cyber-text">{d.headline || "Nothing changed."}</p>
        <span className="text-xs text-cyber-text-faint">{d.generatedMs ? ago(d.generatedMs, now) : d.generated}</span>
      </div>
      {d.changes.length > 0 && (
        <ul className="mt-3 space-y-2">
          {d.changes.map((c, i) => (
            <li key={i} className="text-sm">
              <span className="text-cyber-text">{c.what}</span>
              <span className="text-cyber-text-faint"> · {c.area}</span>
              {c.why && <div className="text-cyber-text-dim">{c.why}</div>}
            </li>
          ))}
        </ul>
      )}
      {failed.map((x) => (
        <div key={x.step} className="mt-2 break-words text-sm text-danger">
          Step {x.step} failed: {x.detail}
        </div>
      ))}
    </Card>
  );
}

const DOT = { green: "bg-success", amber: "bg-warning", red: "bg-danger", neutral: "bg-cyber-text-faint" } as const;

function FeedCard({ f, now, advanced, onStudy }: { f: LabFeed; now: number; advanced: boolean; onStudy: (name: string) => void }) {
  const [all, setAll] = useState(false);
  const t = feedTone(f.status);
  const items = all ? f.items : f.items.slice(0, 5);
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span aria-label={t.label} className={`h-2 w-2 shrink-0 rounded-full ${DOT[t.tone]}`} />
          <span className="text-[15px] font-semibold text-cyber-text">{f.title}</span>
          {advanced && !f.conforms && (
            <Badge tone="neutral" title="This report does not carry the common feed header (docs/LAB-FEEDS.md).">
              older format
            </Badge>
          )}
        </div>
        <span className="text-xs text-cyber-text-faint">{ago(f.updatedMs, now)}</span>
      </div>
      {f.headline && <p className="mt-1.5 text-sm leading-relaxed text-cyber-text-dim">{f.headline}</p>}
      {items.length > 0 && (
        <ul className="mt-3 divide-y divide-cyber-border">
          {items.map((it, i) => {
            const study = it.link ? studyLink(it.link) : null;
            const web = it.link && /^https?:\/\//.test(it.link) ? it.link : null;
            return (
              <li key={i} className="flex items-start justify-between gap-3 py-2 text-sm">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 text-cyber-text">
                    {it.status && <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT[feedTone(it.status).tone]}`} />}
                    {study ? (
                      <button type="button" onClick={() => onStudy(study)} className="text-left hover:underline">
                        {it.label}
                      </button>
                    ) : web ? (
                      <a href={web} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 hover:underline">
                        {it.label}
                        <ExternalLink size={11} aria-hidden />
                      </a>
                    ) : (
                      it.label
                    )}
                  </div>
                  {it.detail && <div className="text-cyber-text-dim">{it.detail}</div>}
                </div>
                {it.value && <div className="shrink-0 font-mono tabular-nums text-cyber-text">{it.value}</div>}
              </li>
            );
          })}
        </ul>
      )}
      {f.items.length > 5 && (
        <button type="button" onClick={() => setAll((a) => !a)} className="mt-2 text-xs font-medium text-accent hover:underline">
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
    <div className="divide-y divide-cyber-border overflow-hidden rounded-xl border border-cyber-border bg-cyber-surface">
      {studies.map((s) => {
        const isOpen = open === s.id;
        const v = verdictBadge(s.kind);
        const md = s.file ? docs[s.file] : undefined;
        return (
          <div key={s.id} id={`study-${s.id}`} className="scroll-mt-4">
            <button
              type="button"
              onClick={() => setOpen(isOpen ? null : s.id)}
              aria-expanded={isOpen}
              className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-cyber-surface-2/50"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-sm font-medium text-cyber-text">{s.title}</span>
                  <Badge tone={v.tone}>{v.label}</Badge>
                </div>
                <p className="mt-1 text-sm leading-relaxed text-cyber-text-dim">{s.verdict}</p>
                <div className="mt-1 text-xs text-cyber-text-faint">
                  {s.date ?? "undated"}
                  {advanced && ` · ${s.code}`}
                </div>
              </div>
              <ChevronDown size={16} aria-hidden className={`mt-0.5 shrink-0 text-cyber-text-faint transition-transform ${isOpen ? "rotate-180" : ""}`} />
            </button>
            {isOpen && (
              <div className="border-t border-cyber-border bg-cyber-bg/30 px-4 py-4">
                {md ? (
                  <Markdown source={md} onStudy={onStudy} />
                ) : (
                  <p className="text-sm text-cyber-text-dim">
                    There is no separate write-up for this one; the answer above is the lab's summary of it.
                  </p>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
