import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { alertsAvailable, fetchAlerts, fetchEvents, sendTest, setMute } from "./alerts";

// The server address comes from the build's env; here it is a plain switch.
const server = vi.hoisted(() => ({ url: null as string | null }));
vi.mock("../engine/serverEngine", () => ({ serverUrl: () => server.url }));

type Call = { url: string; init?: RequestInit };

function stubFetch(status: number, body: unknown): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response(typeof body === "string" ? body : JSON.stringify(body), { status });
  });
  return calls;
}

describe("alerts calls", () => {
  beforeEach(() => {
    server.url = "http://engine.test";
  });
  afterEach(() => vi.unstubAllGlobals());

  it("need the server", async () => {
    server.url = null;
    expect(alertsAvailable()).toBe(false);
    expect((await fetchAlerts()).ok).toBe(false);
  });

  it("read GET /api/alerts", async () => {
    const calls = stubFetch(200, { enabled: true, destination: "discord", mutedUntilMs: 0, counts: { sentToday: 1, failedToday: 0, suppressedToday: 0 }, recent: [], lastDigest: null });
    const r = await fetchAlerts();
    expect(calls[0].url).toBe("http://engine.test/api/alerts");
    expect(r.ok && r.data.destination).toBe("discord");
  });

  it("mute with {minutes}", async () => {
    const calls = stubFetch(200, { mutedUntilMs: 123 });
    const r = await setMute(60);
    expect(calls[0].url).toBe("http://engine.test/api/alerts/mute");
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ minutes: 60 });
    expect(r.ok && r.data.mutedUntilMs).toBe(123);
  });

  it("show the server's reason when a mute is refused", async () => {
    stubFetch(400, { error: "minutes must be 0 to 10080 (seven days)" });
    expect(await setMute(99_999)).toEqual({ ok: false, error: "minutes must be 0 to 10080 (seven days)" });
  });

  it("say why a test message did not arrive", async () => {
    stubFetch(502, { ts: 1, kinds: ["test"], text: "Test", delivered: false, error: "HTTP 500" });
    expect(await sendTest()).toEqual({ ok: false, error: "Not delivered: HTTP 500" });
    stubFetch(409, { error: "alerts are not configured" });
    expect(await sendTest()).toEqual({ ok: false, error: "alerts are not configured" });
  });

  it("take the events ring from GET /api/state", async () => {
    const calls = stubFetch(200, { events: [{ id: "e1", ts: 1, kind: "fill", message: "Paper FILL Buy 1 BTC/USD @ 1", mode: "paper" }] });
    const r = await fetchEvents();
    expect(calls[0].url).toBe("http://engine.test/api/state");
    expect(r.ok && r.data.map((e) => e.id)).toEqual(["e1"]);
    stubFetch(200, {});
    const empty = await fetchEvents();
    expect(empty.ok && empty.data).toEqual([]);
  });
});
