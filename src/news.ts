// Pythia News (GET /api/lab/news, /api/lab/news/{id}): the lab's events as
// German articles, written every 30 minutes by the lab job `news`
// (research/lab/lab/ops/news.py) from its own reports. Read only: nothing here
// trades or changes a setting. "Neu seit deinem letzten Besuch" is kept in this
// browser's local storage, nowhere else.

import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";
import { pageQuery } from "./deepLink";

export const CATEGORIES = ["Forschung", "Fabrik", "Modelle", "Daten", "Geld", "Betrieb", "Warnung"] as const;
export type Category = (typeof CATEGORIES)[number];

/** The page reads the list again every 2 minutes while it is shown. */
export const NEWS_POLL_MS = 120_000;
export const NEWS_PER_PAGE = 30;
const SEEN_KEY = "pythia.news.lastVisit";

export interface KeyNumber {
  label: string;
  value: string;
}

export interface Article {
  id: string;
  timeMs: number;
  category: string;
  headline: string;
  teaser: string;
  /** Markdown; only in the single article (the list leaves it out). */
  body: string | null;
  tags: string[];
  /** Lab Live node ids the article is about (book:tsmom, model:M2, factory:F3, ...). */
  about: string[];
  source: string;
  importance: number;
  key: KeyNumber | null;
  updated: boolean;
  updatedMs: number | null;
}

export interface NewsList {
  found: boolean;
  updatedMs: number | null;
  total: number;
  page: number;
  per: number;
  articles: Article[];
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
const obj = (v: unknown): Record<string, unknown> => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {});

export function parseArticle(r: unknown): Article | null {
  const o = obj(r);
  const id = str(o.id);
  if (!id) return null;
  const k = obj(o.key);
  return {
    id,
    timeMs: num(o.time_ms) ?? 0,
    category: str(o.category) || "Betrieb",
    headline: str(o.headline),
    teaser: str(o.teaser),
    body: typeof o.body === "string" ? o.body : null,
    tags: strs(o.tags),
    about: strs(o.about),
    source: str(o.source),
    importance: Math.max(1, Math.min(3, num(o.importance) ?? 1)),
    key: str(k.label) && str(k.value) ? { label: str(k.label), value: str(k.value) } : null,
    updated: o.updated === true,
    updatedMs: num(o.updated_ms),
  };
}

export function parseNews(raw: unknown): NewsList {
  const o = obj(raw);
  const list = Array.isArray(o.articles) ? o.articles : [];
  return {
    found: o.found === true,
    updatedMs: num(o.updated_ms),
    total: num(o.total) ?? 0,
    page: num(o.page) ?? 0,
    per: num(o.per) ?? NEWS_PER_PAGE,
    articles: list.map(parseArticle).filter((a): a is Article => a != null),
  };
}

export function canReadNews(): boolean {
  return liveMode() === "server";
}

export function newsQuery(q: { page?: number; per?: number; category?: string | null; about?: string | null }): string {
  const p = new URLSearchParams();
  p.set("page", String(q.page ?? 0));
  p.set("per", String(q.per ?? NEWS_PER_PAGE));
  if (q.category) p.set("category", q.category);
  if (q.about) p.set("about", q.about);
  return `?${p.toString()}`;
}

/** GET only: the page never sends anything else. */
async function getJson(path: string): Promise<unknown> {
  const r = await fetch(`${serverUrl()}${path}`, { method: "GET", cache: "no-store" });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`Der Server antwortete ${r.status}`);
  return r.json();
}

export async function fetchNews(q: { page?: number; per?: number; category?: string | null; about?: string | null } = {}): Promise<NewsList> {
  if (!canReadNews()) throw new Error("Pythia News braucht den Server.");
  return parseNews(await getJson(`/api/lab/news${newsQuery(q)}`));
}

export async function fetchArticle(id: string): Promise<Article | null> {
  if (!canReadNews()) throw new Error("Pythia News braucht den Server.");
  return parseArticle(await getJson(`/api/lab/news/${encodeURIComponent(id)}`));
}

// ── what the page shows ──

/** The lead story: the most important of the newest day's articles, else the newest. */
export function leadOf(arts: Article[]): Article | null {
  if (arts.length === 0) return null;
  const day = arts[0].timeMs - 24 * 3600_000;
  const recent = arts.filter((a) => a.timeMs >= day);
  return recent.reduce((best, a) => (a.importance > best.importance ? a : best), recent[0] ?? arts[0]);
}

/** "vor 5 Min.", "vor 3 Std.", "vor 2 Tagen", else the date. */
export function agoText(ms: number, nowMs: number): string {
  const s = Math.max(0, (nowMs - ms) / 1000);
  if (s < 60) return "gerade eben";
  if (s < 3600) return `vor ${Math.floor(s / 60)} Min.`;
  if (s < 86_400) return `vor ${Math.floor(s / 3600)} Std.`;
  if (s < 7 * 86_400) {
    const d = Math.floor(s / 86_400);
    return d === 1 ? "vor 1 Tag" : `vor ${d} Tagen`;
  }
  return dateText(ms);
}

export function dateText(ms: number): string {
  const d = new Date(ms);
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`;
}

export function clockText(ms: number | null | undefined): string {
  if (!ms) return "";
  const d = new Date(ms);
  return `Stand ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export type Tone = "neutral" | "good" | "warn" | "bad" | "accent";

export const CATEGORY_TONE: Record<string, Tone> = {
  Forschung: "accent",
  Fabrik: "neutral",
  Modelle: "accent",
  Daten: "neutral",
  Geld: "good",
  Betrieb: "neutral",
  Warnung: "bad",
};

/** The Lab Live node an id names, in words ("Buch tsmom", "Modell M2"). */
export function nodeLabel(id: string): string {
  const [kind, ...rest] = id.split(":");
  const name = rest.join(":");
  const word: Record<string, string> = { book: "Buch", model: "Modell", factory: "Fabrik", bot: "Bot", job: "Job", src: "Quelle" };
  return `${word[kind] ?? kind} ${name}`.trim();
}

/** The link that opens Lab Live on a node (embedded when this page is). */
export function nodeHref(id: string, embed: boolean): string {
  return `${pageQuery("lablive", embed)}&node=${encodeURIComponent(id)}`;
}

/** The link that opens one article. */
export function articleHref(id: string, embed: boolean): string {
  return `${pageQuery("news", embed)}&article=${encodeURIComponent(id)}`;
}

// ── "neu seit deinem letzten Besuch" ──

type Store = Pick<Storage, "getItem" | "setItem">;

function store(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** When this browser last saw the news page (0 the first time). */
export function lastVisit(s: Store | null = store()): number {
  const v = Number(s?.getItem(SEEN_KEY) ?? 0);
  return Number.isFinite(v) && v > 0 ? v : 0;
}

export function markVisit(ms: number, s: Store | null = store()): void {
  try {
    s?.setItem(SEEN_KEY, String(Math.round(ms)));
  } catch {
    // private mode: no memory, every article stays as it was
  }
}

/** New or updated since the last visit; nothing is new on the very first visit. */
export function isNew(a: Article, since: number): boolean {
  return since > 0 && Math.max(a.timeMs, a.updatedMs ?? 0) > since;
}
