// Lab Live: an animated map of everything that runs in the lab, from the data
// to the models, the books and the money (GET /api/lab/live, written every 5
// minutes by the lab job `lablive`). Columns left to right; small pulses travel
// along the edges while a node runs, colour by state, a gentle idle motion
// (none with prefers-reduced-motion). On a phone the map becomes a stacked list.
// A click opens a side panel: what the node does, what it does now, its
// numbers with a sparkline, inputs and outputs (clickable), its last runs and
// log lines, and the news articles about it. Read every 30 s while shown.
// Opens on its own with `?page=lablive&embed=1` (one node: `&node=<id>`).
// Read only: nothing here trades or changes a setting.

import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, X } from "lucide-react";
import { Chip, Notice, Page, Sparkline } from "../design";
import { LoadingRows, Nothing } from "../pagekit";
import { useVisiblePoll } from "../pageVisible";
import { currentDeepLink } from "../deepLink";
import { agoText, articleHref, canReadNews, fetchNews, type Article } from "../news";
import {
  COLUMNS,
  COLUMN_LABEL,
  LIVE_POLL_MS,
  MAP,
  STATES,
  STATE_COLOR,
  STATE_LABEL,
  canReadLive,
  edgePath,
  fetchLive,
  layout,
  neighbours,
  onNodeRequest,
  prefersReducedMotion,
  pulsing,
  queryParam,
  takePendingNode,
  whenText,
  type LiveGraph,
  type LiveNode,
  type NodeState,
} from "../lablive";

const NARROW = "(max-width: 767px)";
const MAX_PULSES = 80;

function useMedia(q: string): boolean {
  const [on, setOn] = useState(() => (typeof window === "undefined" ? false : window.matchMedia?.(q).matches ?? false));
  useEffect(() => {
    const mq = window.matchMedia?.(q);
    if (!mq) return;
    const h = () => setOn(mq.matches);
    h();
    mq.addEventListener("change", h);
    return () => mq.removeEventListener("change", h);
  }, [q]);
  return on;
}

const STYLE = `
@keyframes ll-float { 0%, 100% { transform: translateY(0) } 50% { transform: translateY(-1.5px) } }
@keyframes ll-breathe { 0%, 100% { opacity: .25 } 50% { opacity: .7 } }
@keyframes ll-flow { to { stroke-dashoffset: -20 } }
.ll-float { animation: ll-float 6s ease-in-out infinite; }
.ll-breathe { animation: ll-breathe 1.8s ease-in-out infinite; }
.ll-flow { stroke-dasharray: 4 6; animation: ll-flow 1.2s linear infinite; }
@media (prefers-reduced-motion: reduce) { .ll-float, .ll-breathe, .ll-flow { animation: none; } }
`;

function short(s: string, n: number): string {
  return s.length <= n ? s : `${s.slice(0, n - 1)}…`;
}

function Dot({ state, size = 8 }: { state: NodeState; size?: number }) {
  return <span aria-hidden className="inline-block shrink-0 rounded-full" style={{ width: size, height: size, background: STATE_COLOR[state] }} />;
}

/** The map (rendered by tests without a server). */
export function LiveMap({
  g,
  selected,
  onSelect,
  hideOff,
  reduced,
}: {
  g: LiveGraph;
  selected: string | null;
  onSelect: (id: string) => void;
  hideOff: boolean;
  reduced: boolean;
}) {
  const L = useMemo(() => layout(g, hideOff), [g, hideOff]);
  const [hover, setHover] = useState<string | null>(null);
  const focus = hover ?? selected;
  const near = useMemo(() => (focus ? neighbours(g, focus) : null), [g, focus]);
  const pulses = useMemo(() => (reduced ? [] : pulsing(g).slice(0, MAX_PULSES)), [g, reduced]);
  const edges = g.edges.filter((e) => L.placed.has(e.from) && L.placed.has(e.to));
  return (
    <div className="overflow-x-auto rounded-card border border-line bg-surface" data-map="">
      <svg width={L.width} height={L.height} viewBox={`0 0 ${L.width} ${L.height}`} role="img" aria-label="Karte des Labors: Daten, Modelle, Bücher und Geld" className="block">
        <style>{STYLE}</style>
        {L.columns.map((c) => (
          <text key={c.id} x={c.x} y={22} fontSize={12} fontWeight={600} fill="var(--color-muted)">
            {COLUMN_LABEL[c.id]} ({c.count})
          </text>
        ))}
        <g fill="none">
          {edges.map((e) => {
            const a = L.placed.get(e.from)!;
            const b = L.placed.get(e.to)!;
            const lit = near != null && near.has(e.from) && near.has(e.to) && (e.from === focus || e.to === focus);
            const running = a.node.state === "running";
            return (
              <path
                key={`${e.from}>${e.to}`}
                d={edgePath(a, b)}
                stroke={lit ? "var(--color-accent)" : "var(--color-line-strong)"}
                strokeOpacity={near && !lit ? 0.25 : lit ? 0.95 : 0.6}
                strokeWidth={lit ? 1.6 : 1}
                className={running && !reduced ? "ll-flow" : undefined}
              />
            );
          })}
        </g>
        {pulses.map((e, i) => {
          const a = L.placed.get(e.from);
          const b = L.placed.get(e.to);
          if (!a || !b) return null;
          return (
            <circle key={`p${e.from}>${e.to}`} r={3} fill="var(--color-accent)" data-pulse="">
              <animateMotion dur="2.4s" begin={`${(i % 8) * 0.3}s`} repeatCount="indefinite" path={edgePath(a, b)} />
            </circle>
          );
        })}
        {[...L.placed.values()].map(({ node: n, x, y }, i) => {
          const sel = n.id === selected;
          const dim = near != null && !near.has(n.id);
          return (
            <g key={n.id} transform={`translate(${x},${y})`} opacity={dim ? 0.45 : 1}>
              <g className={reduced ? undefined : "ll-float"} style={reduced ? undefined : { animationDelay: `${(i % 11) * 0.5}s` }}>
                {n.state === "running" && !reduced && <rect className="ll-breathe" x={-3} y={-3} width={MAP.nodeW + 6} height={MAP.nodeH + 6} rx={11} fill="var(--color-accent)" />}
                <rect
                  role="button"
                  tabIndex={0}
                  aria-label={`${n.name}, ${STATE_LABEL[n.state]}`}
                  data-node={n.id}
                  data-state={n.state}
                  width={MAP.nodeW}
                  height={MAP.nodeH}
                  rx={8}
                  fill="var(--color-surface)"
                  stroke={sel ? "var(--color-accent)" : STATE_COLOR[n.state]}
                  strokeWidth={sel ? 2.2 : 1.2}
                  style={{ cursor: "pointer" }}
                  onClick={() => onSelect(n.id)}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect(n.id)}
                  onMouseEnter={() => setHover(n.id)}
                  onMouseLeave={() => setHover(null)}
                />
                <circle cx={13} cy={MAP.nodeH / 2} r={4} fill={STATE_COLOR[n.state]} pointerEvents="none" />
                <text x={24} y={MAP.nodeH / 2 + 4} fontSize={12} fill="var(--color-text)" pointerEvents="none">
                  {short(n.name, 23)}
                </text>
              </g>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** The phone's stacked list (rendered by tests without a server). */
export function LiveList({ g, onSelect, hideOff }: { g: LiveGraph; onSelect: (id: string) => void; hideOff: boolean }) {
  return (
    <div className="space-y-4" data-list="">
      {COLUMNS.map((c) => {
        const ns = g.nodes.filter((n) => n.column === c && !(hideOff && n.state === "off"));
        if (ns.length === 0) return null;
        return (
          <section key={c} aria-label={COLUMN_LABEL[c]}>
            <h2 className="px-1 pb-1 text-[13px] font-semibold text-muted">{COLUMN_LABEL[c]}</h2>
            <ul className="divide-y divide-line rounded-card border border-line bg-surface">
              {ns.map((n) => (
                <li key={n.id}>
                  <button type="button" onClick={() => onSelect(n.id)} data-node={n.id} className="flex w-full items-center gap-3 px-4 py-2.5 text-left">
                    <Dot state={n.state} size={10} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[14px] font-semibold text-ink">{n.name}</span>
                      <span className="block truncate text-[12px] text-muted">{n.now || STATE_LABEL[n.state]}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

/** Everything about one node (rendered by tests without a server). */
export function NodePanel({
  g,
  n,
  articles,
  embed,
  nowMs,
  onSelect,
  onClose,
}: {
  g: LiveGraph;
  n: LiveNode;
  articles: Article[] | null;
  embed: boolean;
  nowMs: number;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const byId = new Map(g.nodes.map((x) => [x.id, x]));
  const link = (id: string) => {
    const x = byId.get(id);
    return (
      <li key={id}>
        <button type="button" onClick={() => onSelect(id)} data-goto={id} className="flex items-center gap-2 text-left text-[13px] text-accent hover:underline">
          <Dot state={x?.state ?? "ok"} /> {x?.name ?? id}
        </button>
      </li>
    );
  };
  return (
    <aside
      aria-label={`Details: ${n.name}`}
      data-panel={n.id}
      className="pt-scroll fixed inset-y-0 right-0 z-40 w-full max-w-md overflow-y-auto border-l border-line bg-surface p-5 shadow-xl"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[12px] text-muted">
            {COLUMN_LABEL[n.column]} · {n.kind}
          </p>
          <h2 className="text-[20px] font-bold leading-tight text-ink">{n.name}</h2>
        </div>
        <button type="button" onClick={onClose} aria-label="Schließen" className="rounded-full p-1.5 text-muted hover:bg-surface-2 hover:text-ink">
          <X size={18} aria-hidden />
        </button>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2.5 py-0.5 text-xs font-semibold text-ink">
          <Dot state={n.state} /> {STATE_LABEL[n.state]}
        </span>
        {n.schedule && <Chip>{n.schedule}</Chip>}
      </div>
      <p className="mt-3 text-[14px] leading-relaxed text-ink">{n.what}</p>
      {n.detail && <p className="mt-1 text-[13px] leading-relaxed text-muted">{n.detail}</p>}
      <h3 className="mt-4 text-[13px] font-semibold text-ink">Gerade</h3>
      <p className="text-[13px] text-muted">{n.now || STATE_LABEL[n.state]}</p>
      <p className="mt-1 text-[12px] text-faint">
        Letzter Lauf {whenText(n.lastRun)} · nächster {whenText(n.nextRun)}
      </p>
      {n.numbers.length > 0 && (
        <>
          <h3 className="mt-4 text-[13px] font-semibold text-ink">Zahlen</h3>
          <dl className="mt-1 grid grid-cols-2 gap-x-4 gap-y-1 text-[13px]">
            {n.numbers.map((x) => (
              <div key={x.label} className="contents">
                <dt className="text-muted">{x.label}</dt>
                <dd className="tabular text-right font-semibold text-ink">{x.value}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
      {n.spark.length >= 2 && (
        <div className="mt-3">
          <Sparkline data={n.spark} height={40} label={n.sparkLabel || "Verlauf"} />
          <p className="mt-1 text-[11px] text-faint">{n.sparkLabel}</p>
        </div>
      )}
      <div className="mt-4 grid grid-cols-2 gap-4">
        <div>
          <h3 className="text-[13px] font-semibold text-ink">Eingänge</h3>
          {n.inputs.length ? <ul className="mt-1 space-y-1">{n.inputs.map(link)}</ul> : <p className="text-[12px] text-faint">keine</p>}
        </div>
        <div>
          <h3 className="text-[13px] font-semibold text-ink">Ausgänge</h3>
          {n.outputs.length ? <ul className="mt-1 space-y-1">{n.outputs.map(link)}</ul> : <p className="text-[12px] text-faint">keine</p>}
        </div>
      </div>
      {n.runs.length > 0 && (
        <>
          <h3 className="mt-4 text-[13px] font-semibold text-ink">Letzte Läufe</h3>
          <ul className="mt-1 space-y-0.5 text-[12px]">
            {n.runs.map((r, i) => (
              <li key={i} className="flex justify-between gap-2">
                <span className="tabular text-muted">{whenText(r.start)}</span>
                <span className={r.status === "ok" ? "text-up" : "text-down"}>
                  {r.status ?? "-"}
                  {r.durationS != null ? ` · ${Math.round(r.durationS)} s` : ""}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      {n.logs.length > 0 && (
        <>
          <h3 className="mt-4 text-[13px] font-semibold text-ink">Letzte Logzeilen</h3>
          <pre className="mt-1 max-h-48 overflow-auto rounded-lg bg-surface-2 p-2 font-mono text-[11px] leading-snug text-muted">{n.logs.join("\n")}</pre>
        </>
      )}
      <h3 className="mt-4 text-[13px] font-semibold text-ink">In Pythia News</h3>
      {articles == null ? (
        <p className="text-[12px] text-faint">wird geladen</p>
      ) : articles.length === 0 ? (
        <p className="text-[12px] text-faint">Noch kein Artikel über diesen Knoten.</p>
      ) : (
        <ul className="mt-1 space-y-2">
          {articles.map((a) => (
            <li key={a.id}>
              <a href={articleHref(a.id, embed)} data-article={a.id} className="block text-[13px] font-semibold leading-snug text-accent hover:underline">
                {a.headline}
              </a>
              <span className="text-[11px] text-faint">
                {a.category} · {agoText(a.timeMs, nowMs)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

/** The legend and the off switch (rendered by tests without a server). */
export function LiveLegend({ g, hideOff, onHideOff }: { g: LiveGraph; hideOff: boolean; onHideOff: (v: boolean) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-1 text-[12px] text-muted">
      {STATES.map((s) => (
        <span key={s} className="inline-flex items-center gap-1.5" data-count={s}>
          <Dot state={s} /> {STATE_LABEL[s]} <span className="tabular">{g.counts[s]}</span>
        </span>
      ))}
      <label className="ml-auto inline-flex cursor-pointer items-center gap-1.5">
        <input type="checkbox" checked={!hideOff} onChange={(e) => onHideOff(!e.target.checked)} />
        Ausgeschaltete zeigen
      </label>
    </div>
  );
}

export function LabLive() {
  const ref = useRef<HTMLDivElement>(null);
  const [embed] = useState(() => currentDeepLink().embed);
  const [g, setG] = useState<LiveGraph | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(() =>
    typeof window === "undefined" ? null : takePendingNode() ?? queryParam(window.location.search, "node"),
  );
  const [hideOff, setHideOff] = useState(true);
  const [articles, setArticles] = useState<Article[] | null>(null);
  const narrow = useMedia(NARROW);
  const reducedMq = useMedia("(prefers-reduced-motion: reduce)");
  const reduced = reducedMq || prefersReducedMotion();

  useEffect(() => onNodeRequest((id) => setSelected(id)), []);

  const [at] = useVisiblePoll(
    ref,
    () =>
      canReadLive()
        ? fetchLive()
            .then((ng) => {
              setG(ng);
              setErr(null);
            })
            .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
        : undefined,
    LIVE_POLL_MS,
  );

  useEffect(() => {
    setArticles(null);
    if (!selected || !canReadNews()) return;
    let live = true;
    void fetchNews({ about: selected, per: 10 })
      .then((l) => live && setArticles(l.articles))
      .catch(() => live && setArticles([]));
    return () => {
      live = false;
    };
  }, [selected]);

  const node = g && selected ? g.nodes.find((n) => n.id === selected) ?? null : null;
  const stamp = g?.updatedMs ?? at;
  return (
    <div ref={ref}>
      <Page
        wide
        title="Lab Live"
        subtitle="Alles, was im Labor läuft, als Karte: von den Daten über Modelle und Fabriken zu den Paper-Büchern und dem echten Geld. Klicke einen Knoten für alles über ihn."
        right={stamp ? <span className="tabular text-[13px] text-muted">{agoText(stamp, Date.now())}</span> : undefined}
      >
        {!canReadLive() ? (
          <Notice tone="info" title="Braucht den Server" icon={Activity}>
            Die Karte kommt vom verbundenen Server des Labors.
          </Notice>
        ) : err && !g ? (
          <Notice tone="warning" title="Die Karte konnte nicht gelesen werden">
            {err}
          </Notice>
        ) : !g ? (
          <LoadingRows rows={6} label="Die Karte wird geladen" />
        ) : !g.found || g.nodes.length === 0 ? (
          <Nothing icon={Activity} title="Noch keine Karte">
            Der Lab-Job lablive schreibt sie alle 5 Minuten; er ist noch nicht gelaufen.
          </Nothing>
        ) : (
          <>
            <LiveLegend g={g} hideOff={hideOff} onHideOff={setHideOff} />
            {narrow ? (
              <LiveList g={g} onSelect={setSelected} hideOff={hideOff} />
            ) : (
              <LiveMap g={g} selected={selected} onSelect={setSelected} hideOff={hideOff} reduced={reduced} />
            )}
            <p className="px-1 text-[12px] text-faint">
              {g.nodes.length} Knoten, {g.edges.length} Verbindungen. Pulse laufen, solange ein Knoten arbeitet. Nur eine Ansicht: hier wird nichts gehandelt und nichts umgestellt.
            </p>
          </>
        )}
      </Page>
      {g && node && (
        <NodePanel g={g} n={node} articles={articles} embed={embed} nowMs={Date.now()} onSelect={setSelected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
