// Pythia News: the lab's events as a newspaper. A lead story with its key
// number, then a grid of cards (category, time, headline, teaser), category
// chips, and an article view (the body rendered with the app's markdown
// reader, its numbers in bold and tinted, links to the models and books it is
// about, which open Lab Live on that node). "Neu" marks what came since this
// browser's last visit. Read every 2 minutes while shown. Opens on its own
// with `?page=news&embed=1` (one article: `&article=<id>`). Read only:
// nothing here trades or changes a setting.

import { useEffect, useRef, useState, type MouseEvent } from "react";
import { ArrowLeft, Newspaper, RefreshCw } from "lucide-react";
import { Card, Chip, Notice, Page } from "../design";
import { LoadingRows, Nothing } from "../pagekit";
import { Markdown } from "../components/Markdown";
import { useVisiblePoll } from "../pageVisible";
import { currentDeepLink } from "../deepLink";
import { openLabLiveNode, queryParam } from "../lablive";
import {
  CATEGORIES,
  CATEGORY_TONE,
  NEWS_POLL_MS,
  NEWS_PER_PAGE,
  agoText,
  canReadNews,
  clockText,
  dateText,
  fetchArticle,
  fetchNews,
  isNew,
  lastVisit,
  leadOf,
  markVisit,
  nodeHref,
  nodeLabel,
  type Article,
  type NewsList,
} from "../news";

function NewBadge() {
  return <span className="rounded-full bg-accent px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-on-accent">neu</span>;
}

function Meta({ a, nowMs, since }: { a: Article; nowMs: number; since: number }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
      <Chip tone={CATEGORY_TONE[a.category] ?? "neutral"}>{a.category}</Chip>
      <span className="tabular" title={dateText(a.timeMs)}>
        {agoText(a.timeMs, nowMs)}
      </span>
      {a.updated && <span className="text-warn">aktualisiert</span>}
      {isNew(a, since) && <NewBadge />}
    </div>
  );
}

/** A link to Lab Live on one node: in the app it opens the page there, embedded it stays in the frame. */
function NodeLink({ id, embed }: { id: string; embed: boolean }) {
  const onClick = (e: MouseEvent) => {
    if (embed) return;
    e.preventDefault();
    openLabLiveNode(id);
  };
  return (
    <a href={nodeHref(id, embed)} onClick={onClick} data-node={id} className="inline-flex items-center rounded-full bg-surface-2 px-2.5 py-1 text-[12px] font-semibold text-accent hover:underline">
      {nodeLabel(id)}
    </a>
  );
}

function Lead({ a, nowMs, since, onOpen }: { a: Article; nowMs: number; since: number; onOpen: (id: string) => void }) {
  return (
    <Card as="article" className="overflow-hidden">
      <button type="button" onClick={() => onOpen(a.id)} className="block w-full text-left" data-lead={a.id}>
        <Meta a={a} nowMs={nowMs} since={since} />
        <div className="mt-3 grid gap-4 sm:grid-cols-[1fr_auto] sm:items-end">
          <div className="min-w-0">
            <h2 className="font-serif text-[26px] font-bold leading-tight tracking-tight text-ink sm:text-[32px]">{a.headline}</h2>
            <p className="mt-2 text-[16px] leading-relaxed text-muted">{a.teaser}</p>
          </div>
          {a.key && (
            <div className="rounded-xl bg-surface-2 px-4 py-3 text-right" data-key="">
              <div className="tabular text-[30px] font-bold leading-none text-accent">{a.key.value}</div>
              <div className="mt-1 text-[12px] text-muted">{a.key.label}</div>
            </div>
          )}
        </div>
      </button>
    </Card>
  );
}

function Tile({ a, nowMs, since, onOpen }: { a: Article; nowMs: number; since: number; onOpen: (id: string) => void }) {
  return (
    <li>
      <button
        type="button"
        onClick={() => onOpen(a.id)}
        data-article={a.id}
        className="flex h-full w-full flex-col gap-2 rounded-card border border-line bg-surface p-4 text-left transition-colors hover:border-line-strong"
      >
        <Meta a={a} nowMs={nowMs} since={since} />
        <h3 className="text-[16px] font-semibold leading-snug text-ink">{a.headline}</h3>
        <p className="line-clamp-3 text-[14px] leading-relaxed text-muted">{a.teaser}</p>
        {a.key && (
          <p className="mt-auto text-[13px] text-muted">
            {a.key.label}: <span className="tabular font-semibold text-ink">{a.key.value}</span>
          </p>
        )}
      </button>
    </li>
  );
}

/** The front page, given what was read (rendered by tests without a server). */
export function NewsFront({
  list,
  nowMs,
  since,
  category,
  onCategory,
  onOpen,
}: {
  list: NewsList;
  nowMs: number;
  since: number;
  category: string | null;
  onCategory: (c: string | null) => void;
  onOpen: (id: string) => void;
}) {
  const lead = category ? list.articles[0] ?? null : leadOf(list.articles);
  const rest = list.articles.filter((a) => a.id !== lead?.id);
  const fresh = list.articles.filter((a) => isNew(a, since)).length;
  return (
    <>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Rubriken">
        <Chip onClick={() => onCategory(null)} selected={category == null}>
          Alle
        </Chip>
        {CATEGORIES.map((c) => (
          <Chip key={c} onClick={() => onCategory(c)} selected={category === c}>
            {c}
          </Chip>
        ))}
      </div>
      {since > 0 && (
        <p className="px-1 text-[13px] text-muted" data-fresh={fresh}>
          {fresh === 0 ? "Nichts neu seit deinem letzten Besuch." : `${fresh} Artikel neu seit deinem letzten Besuch.`}
        </p>
      )}
      {!lead ? (
        <Nothing icon={Newspaper} title={list.found ? "Keine Artikel in dieser Rubrik" : "Noch keine Ausgabe"}>
          {list.found ? "Wähle eine andere Rubrik oder schau später wieder vorbei." : "Der Lab-Job news schreibt die Artikel alle 30 Minuten; er ist noch nicht gelaufen."}
        </Nothing>
      ) : (
        <>
          <Lead a={lead} nowMs={nowMs} since={since} onOpen={onOpen} />
          {rest.length > 0 && (
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Weitere Artikel">
              {rest.map((a) => (
                <Tile key={a.id} a={a} nowMs={nowMs} since={since} onOpen={onOpen} />
              ))}
            </ul>
          )}
        </>
      )}
    </>
  );
}

/** One article (rendered by tests without a server). */
export function ArticleView({ a, nowMs, since, embed, onBack }: { a: Article; nowMs: number; since: number; embed: boolean; onBack: () => void }) {
  return (
    <article className="space-y-4" data-article-view={a.id}>
      <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-[13px] font-semibold text-accent hover:underline">
        <ArrowLeft size={14} aria-hidden /> Zur Titelseite
      </button>
      <Card>
        <Meta a={a} nowMs={nowMs} since={since} />
        <h2 className="mt-3 font-serif text-[28px] font-bold leading-tight tracking-tight text-ink">{a.headline}</h2>
        <p className="mt-2 text-[17px] font-medium leading-relaxed text-ink">{a.teaser}</p>
        {a.key && (
          <p className="mt-3 text-[14px] text-muted">
            {a.key.label}: <span className="tabular text-[20px] font-bold text-accent">{a.key.value}</span>
          </p>
        )}
        <p className="mt-2 text-[12px] text-faint">
          {dateText(a.timeMs)}
          {a.updated && a.updatedMs ? ` · aktualisiert ${dateText(a.updatedMs)}` : ""}
        </p>
        <div className="fl mt-5 [&_strong]:rounded [&_strong]:bg-surface-2 [&_strong]:px-1 [&_strong]:text-accent">
          {a.body ? <Markdown source={a.body} /> : <p className="text-muted">Der Text wird geladen.</p>}
        </div>
        {a.about.length > 0 && (
          <div className="mt-6 border-t border-line pt-4">
            <p className="mb-2 text-[13px] font-semibold text-ink">Worum es geht, auf der Karte Lab Live</p>
            <div className="flex flex-wrap gap-2">
              {a.about.map((id) => (
                <NodeLink key={id} id={id} embed={embed} />
              ))}
            </div>
          </div>
        )}
        {a.source && (
          <p className="mt-4 text-[12px] text-faint">
            Quelle: <code className="font-mono">{a.source}</code>
          </p>
        )}
      </Card>
    </article>
  );
}

/** Up to `n` articles from the start, in pages of 100 (the server's largest). */
async function readFront(n: number, category: string | null): Promise<NewsList> {
  const first = await fetchNews({ page: 0, per: Math.min(n, 100), category });
  const articles = [...first.articles];
  for (let p = 1; articles.length < Math.min(n, first.total) && p < 3; p++) {
    const more = await fetchNews({ page: p, per: 100, category });
    if (more.articles.length === 0) break;
    articles.push(...more.articles);
  }
  return { ...first, articles: articles.slice(0, n) };
}

export function News() {
  const ref = useRef<HTMLDivElement>(null);
  const [embed] = useState(() => currentDeepLink().embed);
  const [since] = useState(() => lastVisit());
  const [list, setList] = useState<NewsList | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [count, setCount] = useState(NEWS_PER_PAGE);
  const [open, setOpen] = useState<string | null>(() => (typeof window === "undefined" ? null : queryParam(window.location.search, "article")));
  const [article, setArticle] = useState<Article | null>(null);

  const read = () =>
    canReadNews()
      ? readFront(count, category)
          .then((l) => {
            setList(l);
            setErr(null);
            markVisit(Date.now());
          })
          .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      : undefined;
  const [at, refresh] = useVisiblePoll(ref, read, NEWS_POLL_MS);

  // A new rubric or more articles: read at once (the first read is the poll's).
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    void read();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category, count]);

  useEffect(() => {
    if (!open) {
      setArticle(null);
      return;
    }
    const fromList = list?.articles.find((a) => a.id === open) ?? null;
    setArticle(fromList);
    if (!canReadNews()) return;
    let live = true;
    void fetchArticle(open)
      .then((a) => live && setArticle(a ?? fromList))
      .catch(() => {});
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const openArticle = (id: string) => {
    setOpen(id);
    ref.current?.closest("[data-scroll-container]")?.scrollTo?.({ top: 0 });
  };
  const nowMs = Date.now();
  return (
    <div ref={ref}>
      <Page
        wide
        title="Pythia News"
        subtitle="Was im Labor passiert, als Zeitung: Forschung, Fabriken, Modelle, Daten, Geld und Betrieb, aus den eigenen Berichten geschrieben."
        right={
          <span className="flex items-center gap-2">
            {(list?.updatedMs ?? at) && <span className="tabular text-[13px] text-muted">{clockText(list?.updatedMs ?? at)}</span>}
            <button type="button" onClick={() => void refresh()} aria-label="Neu laden" className="rounded-full p-1.5 text-muted hover:bg-surface-2 hover:text-ink">
              <RefreshCw size={15} aria-hidden />
            </button>
          </span>
        }
      >
        {!canReadNews() ? (
          <Notice tone="info" title="Braucht den Server" icon={Newspaper}>
            Die Artikel kommen vom verbundenen Server des Labors.
          </Notice>
        ) : err && !list ? (
          <Notice tone="warning" title="Die Zeitung konnte nicht gelesen werden">
            {err}
          </Notice>
        ) : open ? (
          article ? (
            <ArticleView a={article} nowMs={nowMs} since={since} embed={embed} onBack={() => setOpen(null)} />
          ) : (
            <LoadingRows rows={6} label="Der Artikel wird geladen" />
          )
        ) : !list ? (
          <LoadingRows rows={6} label="Die Zeitung wird geladen" />
        ) : (
          <>
            <NewsFront list={list} nowMs={nowMs} since={since} category={category} onCategory={setCategory} onOpen={openArticle} />
            {list.articles.length < list.total && count < 300 && (
              <div className="flex justify-center">
                <button type="button" onClick={() => setCount(count + NEWS_PER_PAGE)} className="rounded-full bg-surface-2 px-4 py-2 text-[13px] font-semibold text-ink hover:bg-raised">
                  Ältere Artikel
                </button>
              </div>
            )}
          </>
        )}
      </Page>
    </div>
  );
}
