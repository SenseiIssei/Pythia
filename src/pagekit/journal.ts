// What each kind of journal line means, in words, and the counts the Journal
// and Dashboard show on top.

import type { ChipTone } from "../design/flows";
import type { JournalEntry, JournalKind } from "../types";

export interface KindInfo {
  label: string;
  help: string;
  tone: ChipTone;
}

export const JOURNAL_KINDS: Record<JournalKind, KindInfo> = {
  signal: { label: "Signal", help: "A strategy decided it wants to buy or sell.", tone: "neutral" },
  order: { label: "Order", help: "An order was sent.", tone: "neutral" },
  fill: { label: "Filled", help: "An order was filled: the trade happened.", tone: "good" },
  reject: { label: "Refused", help: "An order was refused, with the reason.", tone: "bad" },
  risk: { label: "Risk", help: "The risk manager stepped in or a limit changed.", tone: "warn" },
  system: { label: "System", help: "Something about the engine itself.", tone: "neutral" },
};

/** The kind's words, with a fallback for a kind this build does not know. */
export function kindInfo(kind: string): KindInfo {
  return JOURNAL_KINDS[kind as JournalKind] ?? { label: kind, help: "", tone: "neutral" };
}

export type JournalFilter = JournalKind | "all";

/** How many lines of each kind, plus "all". */
export function journalCounts(entries: JournalEntry[]): Record<JournalFilter, number> {
  const out: Record<JournalFilter, number> = { all: entries.length, signal: 0, order: 0, fill: 0, reject: 0, risk: 0, system: 0 };
  for (const e of entries) if (e.kind in out) out[e.kind] += 1;
  return out;
}

/** Lines of one kind, newest first as they come. */
export function filterJournal(entries: JournalEntry[], f: JournalFilter): JournalEntry[] {
  return f === "all" ? entries : entries.filter((e) => e.kind === f);
}

/** Demo-route lines start with DEMO; the engine writes them that way. */
export function isDemoLine(e: JournalEntry): boolean {
  return e.message.startsWith("DEMO");
}
