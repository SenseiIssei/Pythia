import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { LAB_SENT_FEED, LabSwitches, parseLabSent, realCountsLine } from "./pages/Notifications";
import type { LabFeed } from "./labFeeds";

const NOW = new Date(2026, 9, 27, 18, 0).getTime();

function feed(updatedMs: number, items: [string, string, string?][]): LabFeed {
  return {
    name: LAB_SENT_FEED,
    title: "Messages sent by the lab",
    updatedMs,
    status: "ok",
    headline: "",
    conforms: true,
    items: items.map(([label, value, detail]) => ({ label, value, detail: detail ?? null, status: null, link: null, importance: null, atMs: null })),
  };
}

const ITEMS: [string, string, string?][] = [
  ["count:sent", "4"],
  ["count:failed", "1"],
  ["count:held", "2"],
  ["count:off", "3"],
  ["via:telegram", "3"],
  ["via:discord", "1"],
  ["cat:dailyPnl", "2"],
  ["cat:studies", "2"],
  ["switch:pumpfunPaper", "off", "pump.fun paper cards: the shadow winners"],
  ["switch:discordBoth", "on", "Discord in both languages"],
];

describe("the lab's sent log in the notifications page", () => {
  it("reads today's counts and the switches from the lab feed", () => {
    const lab = parseLabSent([feed(NOW - 3_600_000, ITEMS)], NOW)!;
    expect([lab.sent, lab.failed, lab.held, lab.off]).toEqual([4, 1, 2, 3]);
    expect(lab.via).toEqual([["telegram", 3], ["discord", 1]]);
    expect(lab.categories).toEqual([["dailyPnl", 2], ["studies", 2]]);
    expect(lab.switches.map((w) => [w.label, w.on])).toEqual([["pump.fun paper cards", false], ["Discord in both languages", true]]);
  });

  it("does not count yesterday's numbers as today's, but keeps the switches", () => {
    const lab = parseLabSent([feed(NOW - 30 * 3_600_000, ITEMS)], NOW)!;
    expect([lab.sent, lab.failed, lab.held, lab.off, lab.categories.length]).toEqual([0, 0, 0, 0, 0]);
    expect(lab.switches).toHaveLength(2);
  });

  it("is null without the feed, and the engine's line stays as it was", () => {
    expect(parseLabSent([], NOW)).toBeNull();
    expect(parseLabSent(undefined, NOW)).toBeNull();
    expect(realCountsLine({ sentToday: 2, failedToday: 0, suppressedToday: 1 }, null)).toBe("2 sent today · 1 held back");
  });

  it("adds the lab's posts to the engine's counts", () => {
    const lab = parseLabSent([feed(NOW - 60_000, ITEMS)], NOW);
    expect(realCountsLine({ sentToday: 2, failedToday: 0, suppressedToday: 1 }, lab)).toBe(
      "6 sent today (engine 2, lab 4) · 1 failed · 3 held back · 3 switched off",
    );
    expect(realCountsLine(null, lab)).toBe("4 sent today (engine 0, lab 4) · 1 failed · 2 held back · 3 switched off");
  });

  it("shows the switches read only, off by default, and where they are set", () => {
    const html = renderToStaticMarkup(<LabSwitches lab={parseLabSent([feed(NOW - 60_000, ITEMS)], NOW)} />);
    expect(html).toContain("From the lab, off by default");
    expect(html).toContain("pump.fun paper cards");
    expect(html).toContain("PYTHIA_NOTIFY_ON");
    expect(html).toContain("Sent today by the lab: dailyPnl 2, studies 2");
    expect(html).not.toContain('role="switch"');
    expect(renderToStaticMarkup(<LabSwitches lab={null} />)).toBe("");
  });
});
