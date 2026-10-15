import { describe, expect, it } from "vitest";
import { filterJournal, isDemoLine, journalCounts, kindInfo } from "./journal";
import type { JournalEntry } from "../types";

const e = (id: string, kind: JournalEntry["kind"], message = "x"): JournalEntry => ({ id, ts: 0, kind, message, mode: "paper" });

describe("journal view", () => {
  const lines = [e("1", "fill"), e("2", "fill"), e("3", "reject"), e("4", "system", "DEMO sent buy")];

  it("counts each kind and the total", () => {
    const c = journalCounts(lines);
    expect(c.all).toBe(4);
    expect(c.fill).toBe(2);
    expect(c.reject).toBe(1);
    expect(c.signal).toBe(0);
  });

  it("filters by kind and keeps the order", () => {
    expect(filterJournal(lines, "all")).toHaveLength(4);
    expect(filterJournal(lines, "fill").map((x) => x.id)).toEqual(["1", "2"]);
  });

  it("names kinds in words and copes with an unknown one", () => {
    expect(kindInfo("reject")).toMatchObject({ label: "Refused", tone: "bad" });
    expect(kindInfo("brand-new")).toEqual({ label: "brand-new", help: "", tone: "neutral" });
  });

  it("spots demo lines", () => {
    expect(isDemoLine(lines[3])).toBe(true);
    expect(isDemoLine(lines[0])).toBe(false);
  });
});
