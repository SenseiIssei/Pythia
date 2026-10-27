import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MAP, edgePath, fetchLive, layout, neighbours, parseLive, pulsing, queryParam, takePendingNode, whenText } from "./lablive";
import { LiveLegend, LiveList, LiveMap, NodePanel } from "./pages/LabLive";
import { readDeepLink } from "./deepLink";
import { isPageId } from "./nav";
import { parseArticle } from "./news";

const NOW = 1_793_100_000_000;

function n(id: string, column: string, state: string, over: Record<string, unknown> = {}) {
  return { id, kind: id.split(":")[0], name: id.split(":")[1], column, state, what: `Tut ${id}.`, detail: "", now: "", numbers: [], spark: [], runs: [], logs: [], inputs: [], outputs: [], ...over };
}

const RAW = {
  found: true,
  updated_ms: NOW - 60_000,
  nodes: [
    n("src:recorder", "data", "running", { outputs: ["job:features"] }),
    n("job:features", "features", "running", { inputs: ["src:recorder"], outputs: ["job:models"], schedule: "20 2 * * *" }),
    n("job:models", "models", "ok", {
      inputs: ["job:features"], outputs: ["book:tsmom"], last_run: "2026-10-27T07:40:00Z", next_run: "2026-10-28T07:15:00Z",
      numbers: [{ label: "Dauer zuletzt", value: "1.500 s" }], spark: [900, 1500], spark_label: "Dauer der letzten Läufe in Sekunden",
      runs: [{ start: "2026-10-27T07:15:00Z", status: "ok", duration_s: 1500 }], logs: ["done for <adresse>"],
    }),
    n("book:tsmom", "books", "late", { inputs: ["job:models"] }),
    n("bot:pumpfun", "money", "off", { now: "aus: paused by the owner" }),
    n("job:weird", "nowhere", "strange"),
  ],
  edges: [
    { from: "src:recorder", to: "job:features" },
    { from: "job:features", to: "job:models" },
    { from: "job:models", to: "book:tsmom" },
    { from: "job:models", to: "job:gone" },
  ],
};

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("reading Lab Live", () => {
  it("parses the graph and drops edges to nodes that are not there", () => {
    const g = parseLive(RAW);
    expect(g.found).toBe(true);
    expect(g.nodes).toHaveLength(6);
    expect(g.edges).toHaveLength(3);
    const weird = g.nodes.find((x) => x.id === "job:weird")!;
    expect(weird.column).toBe("outputs");
    expect(weird.state).toBe("ok");
    expect(g.counts).toEqual({ running: 2, ok: 2, late: 1, failed: 0, off: 1 });
    expect(g.nodes[2].runs[0].durationS).toBe(1500);
    expect(parseLive(null)).toMatchObject({ found: false, nodes: [], edges: [] });
  });

  it("lays out columns from data to money and draws edges left to right", () => {
    const g = parseLive(RAW);
    const L = layout(g);
    const rec = L.placed.get("src:recorder")!;
    const bot = L.placed.get("bot:pumpfun")!;
    expect(rec.x).toBeLessThan(L.placed.get("job:models")!.x);
    expect(L.placed.get("book:tsmom")!.x).toBeLessThan(bot.x);
    expect(rec.y).toBe(MAP.top);
    expect(L.width).toBeGreaterThan(bot.x + MAP.nodeW - 1);
    expect(edgePath(rec, L.placed.get("job:features")!)).toMatch(/^M\d+,\d+ C/);
    expect(layout(g, true).placed.has("bot:pumpfun")).toBe(false);
  });

  it("pulses only the edges of running nodes", () => {
    const g = parseLive(RAW);
    expect(pulsing(g).map((e) => e.from)).toEqual(["src:recorder", "job:features"]);
    expect([...neighbours(g, "job:models")].sort()).toEqual(["book:tsmom", "job:features", "job:models"]);
  });

  it("reads small things", () => {
    expect(whenText("2026-10-27T07:40:00Z")).toBe("27.10. 07:40 UTC");
    expect(whenText(null)).toBe("-");
    expect(queryParam("?page=lablive&node=book%3Atsmom", "node")).toBe("book:tsmom");
    expect(queryParam("?node=<script>", "node")).toBeNull();
    expect(takePendingNode()).toBeNull();
  });

  it("only ever GETs", async () => {
    vi.stubEnv("VITE_PYTHIA_SERVER", "/api/pythia");
    const calls: { url: string; method: string }[] = [];
    vi.stubGlobal("fetch", async (u: string, init?: RequestInit) => {
      calls.push({ url: u, method: init?.method ?? "GET" });
      return new Response(JSON.stringify(RAW));
    });
    const g = await fetchLive();
    expect(g.nodes).toHaveLength(6);
    expect(calls).toEqual([{ url: "/api/pythia/api/lab/live", method: "GET" }]);
  });
});

describe("the Lab Live page", () => {
  it("opens embedded", () => {
    expect(isPageId("lablive")).toBe(true);
    expect(readDeepLink("?page=lablive&embed=1")).toEqual({ page: "lablive", embed: true });
  });

  it("draws the map with pulses, and none with reduced motion", () => {
    const g = parseLive(RAW);
    const html = renderToStaticMarkup(<LiveMap g={g} selected="job:models" onSelect={() => {}} hideOff={false} reduced={false} />);
    expect(html).toContain('data-node="job:models"');
    expect(html).toContain('data-state="running"');
    expect(html).toContain("var(--color-warn)");                      // the late book
    expect(html.match(/data-pulse/g)).toHaveLength(2);
    expect(html).toContain("animateMotion");
    expect(html).toContain("ll-float");
    expect(html).toContain("Paper-Bücher");
    const calm = renderToStaticMarkup(<LiveMap g={g} selected={null} onSelect={() => {}} hideOff={false} reduced />);
    expect(calm).not.toContain("animateMotion");
    expect(calm).not.toContain('class="ll-float"');
    expect(calm).toContain("prefers-reduced-motion");
  });

  it("stacks a list on a phone", () => {
    const g = parseLive(RAW);
    const html = renderToStaticMarkup(<LiveList g={g} onSelect={() => {}} hideOff />);
    expect(html).toContain("Daten");
    expect(html).toContain('data-node="src:recorder"');
    expect(html).not.toContain('data-node="bot:pumpfun"');
  });

  it("shows everything about a node in the side panel", () => {
    const g = parseLive(RAW);
    const node = g.nodes.find((x) => x.id === "job:models")!;
    const arts = [parseArticle({ id: "study-y17", time_ms: NOW - 3_600_000, category: "Forschung", headline: "Studie: Y17" })!];
    const html = renderToStaticMarkup(<NodePanel g={g} n={node} articles={arts} embed nowMs={NOW} onSelect={() => {}} onClose={() => {}} />);
    expect(html).toContain("Tut job:models.");
    expect(html).toContain("Dauer zuletzt");
    expect(html).toContain("1.500 s");
    expect(html).toContain('data-goto="job:features"');
    expect(html).toContain('data-goto="book:tsmom"');
    expect(html).toContain("27.10. 07:40 UTC");
    expect(html).toContain("done for &lt;adresse&gt;");
    expect(html).toContain('href="?page=news&amp;embed=1&amp;article=study-y17"');
    expect(html).toContain("<svg");                                  // the sparkline
    const empty = renderToStaticMarkup(<NodePanel g={g} n={g.nodes[4]} articles={[]} embed={false} nowMs={NOW} onSelect={() => {}} onClose={() => {}} />);
    expect(empty).toContain("Noch kein Artikel");
    expect(empty).not.toMatch(/<form|<input/);
  });

  it("has a legend with the counts", () => {
    const g = parseLive(RAW);
    const html = renderToStaticMarkup(<LiveLegend g={g} hideOff onHideOff={() => {}} />);
    expect(html).toContain("läuft gerade");
    expect(html).toContain("Ausgeschaltete zeigen");
  });
});
