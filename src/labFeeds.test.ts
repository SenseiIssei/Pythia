import { describe, expect, it } from "vitest";
import { ago, decay, feedTone, pickInsights, type LabFeed } from "./labFeeds";
import type { ForwardReport, ForwardRow, LearnDigest } from "./lab";

const NOW = 1_800_000_000_000;
const H = 3_600_000;

function feed(name: string, over: Partial<LabFeed> = {}): LabFeed {
  return { name, title: name, updatedMs: NOW - H, status: "ok", headline: "", items: [], conforms: true, ...over };
}

function item(label: string, importance: number | null, over = {}) {
  return { label, value: null, status: null, detail: null, link: null, importance, atMs: null, ...over };
}

function row(over: Partial<ForwardRow>): ForwardRow {
  return {
    kind: "book",
    name: "b",
    label: "Book",
    variant: "",
    since: null,
    days: 10,
    elapsedDays: 10,
    returnPct: 0,
    maxDdPct: null,
    turnover: null,
    costs: null,
    fundingPct: null,
    expected: null,
    position: "inside",
    gate7: { days: 10, daysNeeded: 30, trades: 3, tradesNeeded: 30, tradesLabel: "rebalances", progress: 0.1, ready: false },
    status: "on_track",
    sentence: "On track.",
    mode: null,
    state: null,
    startEquity: null,
    equity: null,
    floorEquity: null,
    btcReturnPct: null,
    fees: null,
    feesShareOfGross: null,
    feesPctOfCapital: null,
    tradesPerDay: null,
    slippage: [],
    labBook: null,
    ...over,
  };
}

describe("decay", () => {
  it("keeps full weight for 36 hours, half until a week, then nothing", () => {
    expect(decay(80, 10 * H)).toBe(80);
    expect(decay(80, 40 * H)).toBe(40);
    expect(decay(80, 8 * 24 * H)).toBe(0);
  });
});

describe("pickInsights", () => {
  it("takes the most important item of each feed, best first, at most three", () => {
    const feeds = [
      feed("listings", { title: "New listings", items: [item("SUI/USD", 85, { value: "new", detail: "Listed today." }), item("HYPE/USD", 90)] }),
      feed("cs2", { items: [item("Case prices", 50)] }),
      feed("trending", { items: [item("PEPE", 30)] }),
      feed("zoo", { items: [item("quiet", 10)] }),
      feed("pokemon", { items: [item("cards", 45)] }),
    ];
    const got = pickInsights(feeds, null, null, NOW);
    expect(got.map((x) => x.source)).toEqual(["listings", "cs2", "pokemon"]);
    expect(got[0].text).toBe("HYPE/USD");
    const sui = pickInsights([feeds[0]], null, null, NOW, 5);
    expect(sui).toHaveLength(1);
  });

  it("formats an item with its value and falls back to the feed's status and time", () => {
    const f = feed("listings", { title: "New listings", status: "watch", items: [item("SUI/USD", 85, { value: "new", detail: "Listed today." })] });
    const [x] = pickInsights([f], null, null, NOW);
    expect(x).toMatchObject({ title: "New listings", text: "SUI/USD: new", detail: "Listed today.", status: "watch", score: 85, atMs: NOW - H });
  });

  it("scores the headline of a bad or watch feed", () => {
    const got = pickInsights(
      [feed("jobs", { status: "bad", headline: "Two jobs failed." }), feed("w", { status: "watch", headline: "Look." }), feed("ok", { headline: "Fine." })],
      null,
      null,
      NOW,
    );
    expect(got.map((x) => [x.source, x.score])).toEqual([
      ["jobs", 60],
      ["w", 35],
    ]);
  });

  it("ages old items and drops anything at or under the floor", () => {
    const old = feed("old", { updatedMs: NOW - 48 * H, items: [item("aged", 60)] });
    const stale = feed("stale", { updatedMs: NOW - 9 * 24 * H, items: [item("gone", 100)] });
    const low = feed("low", { items: [item("meh", 20)] });
    const got = pickInsights([old, stale, low], null, null, NOW);
    expect(got.map((x) => [x.source, x.score])).toEqual([["old", 30]]);
  });

  it("an item's own time beats the feed's", () => {
    const f = feed("x", { items: [item("fresh", 50, { atMs: NOW - H }), item("older", 80, { atMs: NOW - 50 * H })] });
    expect(pickInsights([f], null, null, NOW)[0].text).toBe("fresh");
  });

  it("says when a forward test falls below its band and when a model is promoted", () => {
    const forward: ForwardReport = {
      generated: "",
      generatedMs: NOW - H,
      verdict: "",
      books: [row({ name: "a", label: "Breakout", position: "below", sentence: "Below the range after 12 days." }), row({ name: "b" })],
      autopilots: [],
      engine: null,
    };
    const learn: LearnDigest = {
      generated: "",
      generatedMs: NOW - H,
      headline: "",
      changes: [],
      decisions: [
        { model: "vol_1h", candidate: "v2", champion: "v1", decision: "promoted", why: "1.5 % better" },
        { model: "picks_7d", candidate: null, champion: null, decision: "kept", why: "" },
      ],
      autopilots: [],
      steps: [],
    };
    const got = pickInsights([], forward, learn, NOW);
    expect(got.map((x) => [x.source, x.score, x.text])).toEqual([
      ["forward", 75, "Breakout is below what its backtest expected"],
      ["learn", 70, "A better vol_1h model is now in use"],
    ]);
    expect(got[0].detail).toBe("Below the range after 12 days.");
  });

  it("uses the full forward report and learning loop instead of their feeds", () => {
    const forwardFeed = feed("forward", { items: [item("raw row", 90)] });
    const forward: ForwardReport = { generated: "", generatedMs: NOW, verdict: "", books: [row({ status: "watch" })], autopilots: [], engine: null };
    const got = pickInsights([forwardFeed], forward, null, NOW);
    expect(got.map((x) => x.text)).toEqual(["Book is worth watching"]);
    expect(pickInsights([forwardFeed], null, null, NOW)[0].text).toBe("raw row");
  });

  it("is empty when all is quiet", () => {
    expect(pickInsights([feed("a"), feed("b", { items: [item("x", null)] })], null, null, NOW)).toEqual([]);
  });
});

describe("feedTone and ago", () => {
  it("maps statuses to plain words", () => {
    expect(feedTone("ok")).toEqual({ tone: "green", label: "fine" });
    expect(feedTone("bad").tone).toBe("red");
    expect(feedTone("watch").tone).toBe("amber");
    expect(feedTone("sideways").tone).toBe("neutral");
    expect(feedTone(null).tone).toBe("neutral");
  });

  it("says how long ago", () => {
    expect(ago(NOW - 30_000, NOW)).toBe("just now");
    expect(ago(NOW - 15 * 60_000, NOW)).toBe("15 min ago");
    expect(ago(NOW - 5 * H, NOW)).toBe("5 h ago");
    expect(ago(NOW - 26 * H, NOW)).toBe("yesterday");
    expect(ago(NOW - 72 * H, NOW)).toBe("3 days ago");
    expect(ago(0, NOW)).toBe("");
  });
});
