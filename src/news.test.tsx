import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import {
  agoText,
  articleHref,
  fetchArticle,
  fetchNews,
  isNew,
  lastVisit,
  leadOf,
  markVisit,
  newsQuery,
  nodeHref,
  nodeLabel,
  parseArticle,
  parseNews,
  type Article,
} from "./news";
import { ArticleView, NewsFront } from "./pages/News";
import { readDeepLink } from "./deepLink";
import { isPageId } from "./nav";

const NOW = 1_793_100_000_000;

function raw(id: string, over: Record<string, unknown> = {}) {
  return {
    id, time_ms: NOW - 3_600_000, time: "2026-10-27T12:00:00Z", category: "Forschung", headline: `Schlagzeile ${id}`,
    teaser: "Was passiert ist, in einem Satz.", tags: ["studie"], about: [], source: "results/x.md", importance: 1,
    key: null, updated: false, updated_ms: null, ...over,
  };
}

const LIST = {
  found: true, updated_ms: NOW - 60_000, total: 3, page: 0, per: 30,
  articles: [
    raw("a", { time_ms: NOW - 600_000 }),
    raw("live-pumpfun-aus", { category: "Geld", importance: 3, headline: "Echtgeld-Bot ist aus", key: { label: "Ergebnis gesamt", value: "-0,477 SOL" }, time_ms: NOW - 1_200_000 }),
    raw("old", { time_ms: NOW - 3 * 86_400_000, updated: true, updated_ms: NOW - 1000 }),
    { headline: "no id" },
  ],
};

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("reading the news", () => {
  it("parses the list and drops what has no id", () => {
    const l = parseNews(LIST);
    expect(l.found).toBe(true);
    expect(l.articles.map((a) => a.id)).toEqual(["a", "live-pumpfun-aus", "old"]);
    expect(l.articles[1].key).toEqual({ label: "Ergebnis gesamt", value: "-0,477 SOL" });
    expect(l.articles[0].body).toBeNull();
    expect(parseNews(null)).toMatchObject({ found: false, articles: [], total: 0 });
    expect(parseArticle({ id: "x", importance: 9 })?.importance).toBe(3);
  });

  it("builds the query and the links", () => {
    expect(newsQuery({ page: 1, per: 10, category: "Geld", about: "book:tsmom" })).toBe("?page=1&per=10&category=Geld&about=book%3Atsmom");
    expect(newsQuery({})).toBe("?page=0&per=30");
    expect(nodeHref("book:tsmom", true)).toBe("?page=lablive&embed=1&node=book%3Atsmom");
    expect(nodeHref("model:M2", false)).toBe("?page=lablive&node=model%3AM2");
    expect(articleHref("study-y17", true)).toBe("?page=news&embed=1&article=study-y17");
    expect(nodeLabel("book:tsmom")).toBe("Buch tsmom");
    expect(nodeLabel("factory:F3")).toBe("Fabrik F3");
  });

  it("picks the lead: the most important of the last day", () => {
    const l = parseNews(LIST);
    expect(leadOf(l.articles)?.id).toBe("live-pumpfun-aus");
    expect(leadOf([])).toBeNull();
  });

  it("says when, in German", () => {
    expect(agoText(NOW - 30_000, NOW)).toBe("gerade eben");
    expect(agoText(NOW - 5 * 60_000, NOW)).toBe("vor 5 Min.");
    expect(agoText(NOW - 3 * 3_600_000, NOW)).toBe("vor 3 Std.");
    expect(agoText(NOW - 86_400_000, NOW)).toBe("vor 1 Tag");
    expect(agoText(NOW - 2 * 86_400_000, NOW)).toBe("vor 2 Tagen");
  });

  it("remembers the last visit in local storage; nothing is new the first time", () => {
    const m = new Map<string, string>();
    const s = { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) };
    expect(lastVisit(s)).toBe(0);
    const a = parseArticle(raw("a", { time_ms: NOW }))!;
    expect(isNew(a, 0)).toBe(false);
    markVisit(NOW - 1000, s);
    expect(lastVisit(s)).toBe(NOW - 1000);
    expect(isNew(a, lastVisit(s))).toBe(true);
    expect(isNew(parseArticle(raw("b", { time_ms: NOW - 5000 }))!, NOW - 1000)).toBe(false);
    // An update after the visit is new again.
    expect(isNew(parseArticle(raw("c", { time_ms: NOW - 5000, updated: true, updated_ms: NOW }))!, NOW - 1000)).toBe(true);
  });

  it("only ever GETs, and a missing article is null", async () => {
    vi.stubEnv("VITE_PYTHIA_SERVER", "/api/pythia");
    const calls: { url: string; method: string }[] = [];
    vi.stubGlobal("fetch", async (u: string, init?: RequestInit) => {
      calls.push({ url: u, method: init?.method ?? "GET" });
      if (u.endsWith("/nope")) return new Response(JSON.stringify({ found: false }), { status: 404 });
      if (u.includes("/api/lab/news/")) return new Response(JSON.stringify({ ...raw("a"), body: "## Was\n\nText **12 %**." }));
      return new Response(JSON.stringify(LIST));
    });
    const l = await fetchNews({ category: "Geld" });
    expect(l.articles).toHaveLength(3);
    const a = await fetchArticle("a");
    expect(a?.body).toContain("**12 %**");
    expect(await fetchArticle("nope")).toBeNull();
    expect(calls.map((c) => c.method)).toEqual(["GET", "GET", "GET"]);
    expect(calls[0].url).toBe("/api/pythia/api/lab/news?page=0&per=30&category=Geld");
  });

  it("needs the server", async () => {
    vi.stubEnv("VITE_PYTHIA_SERVER", "");
    await expect(fetchNews()).rejects.toThrow("Server");
  });
});

describe("the News page", () => {
  it("opens embedded", () => {
    expect(isPageId("news")).toBe(true);
    expect(readDeepLink("?page=news&embed=1")).toEqual({ page: "news", embed: true });
    expect(readDeepLink("?page=news&embed=1&article=study-y17")).toEqual({ page: "news", embed: true });
  });

  it("renders the front page: chips, the lead with its key number, the cards, what is new", () => {
    const l = parseNews(LIST);
    const html = renderToStaticMarkup(
      <NewsFront list={l} nowMs={NOW} since={NOW - 900_000} category={null} onCategory={() => {}} onOpen={() => {}} />,
    );
    for (const c of ["Alle", "Forschung", "Fabrik", "Modelle", "Daten", "Geld", "Betrieb", "Warnung"]) expect(html).toContain(`>${c}<`);
    expect(html).toContain('data-lead="live-pumpfun-aus"');
    expect(html).toContain("-0,477 SOL");
    expect(html).toContain('data-article="a"');
    expect(html).toContain('data-article="old"');
    expect(html).toContain("aktualisiert");
    expect(html).toContain("2 Artikel neu seit deinem letzten Besuch.");     // a, and old (updated just now)
    expect(html).not.toMatch(/<form|method="post"/i);
  });

  it("says when there is no paper yet", () => {
    const html = renderToStaticMarkup(
      <NewsFront list={parseNews({ found: false })} nowMs={NOW} since={0} category={null} onCategory={() => {}} onOpen={() => {}} />,
    );
    expect(html).toContain("Noch keine Ausgabe");
    expect(html).not.toContain("neu seit");
  });

  it("renders an article: markdown, the numbers marked, links to Lab Live", () => {
    const a: Article = {
      ...parseArticle(raw("study-y17", { about: ["book:tsmom", "model:M2"], key: { label: "Kennzahl", value: "12 %" } }))!,
      body: "## Was passiert ist\n\nDer Rückgang liegt bei **12,0 %**.\n\n- Rendite: **-2,5 %**",
    };
    const html = renderToStaticMarkup(<ArticleView a={a} nowMs={NOW} since={0} embed onBack={() => {}} />);
    expect(html).toContain("Was passiert ist");
    expect(html).toContain("<strong");
    expect(html).toContain("12,0 %");
    expect(html).toContain("[&amp;_strong]:text-accent");
    expect(html).toContain('href="?page=lablive&amp;embed=1&amp;node=book%3Atsmom"');
    expect(html).toContain("Buch tsmom");
    expect(html).toContain("Modell M2");
    expect(html).toContain("results/x.md");
  });
});
