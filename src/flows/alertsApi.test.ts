import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { alertsAvailable, fetchAlerts, fetchEvents, fetchSettings, saveSettings, sendTest, setMute } from "./alerts";

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

  const settings = {
    categories: [{ id: "trades", label: "Trades", emoji: "💱", about: "x", source: "engine", on: false }],
    quietHours: { enabled: true, start: "23:00", end: "07:00", timezone: "Europe/Berlin" },
    bigMoves: { hourPct: 3, dayPct: 8 },
    quietNow: false,
  };

  it("read GET /api/alerts/settings", async () => {
    const calls = stubFetch(200, settings);
    const r = await fetchSettings();
    expect(calls[0].url).toBe("http://engine.test/api/alerts/settings");
    expect(r.ok && r.data.categories[0].on).toBe(false);
  });

  it("change settings with a patch and show the server's reason when refused", async () => {
    const calls = stubFetch(200, settings);
    const r = await saveSettings({ categories: { trades: false }, quietHours: { start: "22:00" } });
    expect(calls[0].url).toBe("http://engine.test/api/alerts/settings");
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ categories: { trades: false }, quietHours: { start: "22:00" } });
    expect(r.ok).toBe(true);
    stubFetch(400, { error: "quiet hours: start and end are HH:MM, 00:00 to 23:59" });
    expect(await saveSettings({ quietHours: { start: "9pm" } })).toEqual({ ok: false, error: "quiet hours: start and end are HH:MM, 00:00 to 23:59" });
  });
});
