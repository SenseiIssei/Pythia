// Lab feeds: every lab job's reports/<name>/latest.json with the common
// header (docs/LAB-FEEDS.md), read by pythia-core/src/labview.rs and served at
// GET /api/lab/feeds. Plus the study write-ups at GET /api/lab/studies and the
// "three things that matter today" for Home.

import { invoke } from "@tauri-apps/api/core";
import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";
import type { ForwardReport, LearnDigest } from "./lab";

export type FeedStatus = "ok" | "watch" | "bad" | "unknown";

export interface FeedItem {
  label: string;
  value: string | null;
  status: FeedStatus | null;
  detail: string | null;
  /** A web link, or `study:<name>` for a write-up under results/. */
  link: string | null;
  /** 0..100: how much it matters today. */
  importance: number | null;
  atMs: number | null;
}

export interface LabFeed {
  /** The folder name under reports/. */
  name: string;
  title: string;
  updatedMs: number;
  status: FeedStatus;
  headline: string;
  items: FeedItem[];
  /** Whether the file carries the common header. */
  conforms: boolean;
}

export interface Study {
  name: string;
  updatedMs: number;
  markdown: string;
}

async function read<T>(command: string, path: string, what: string): Promise<T> {
  switch (liveMode()) {
    case "native":
      return invoke<T>(command);
    case "server": {
      const r = await fetch(`${serverUrl()}${path}`);
      if (!r.ok) throw new Error(`backend answered ${r.status}`);
      return (await r.json()) as T;
    }
    default:
      throw new Error(`${what} need the desktop app or a connected backend.`);
  }
}

/** Every lab feed, worst status first, then newest. */
export function labFeeds(): Promise<LabFeed[]> {
  return read<LabFeed[]>("lab_feeds", "/api/lab/feeds", "The lab feeds");
}

/** The lab's study write-ups as the lab machine has them now. */
export function labStudies(): Promise<Study[]> {
  return read<Study[]>("lab_studies", "/api/lab/studies", "The lab's write-ups");
}

type Tone = "green" | "amber" | "red" | "neutral";

/** The colour and the plain word for a feed status. */
export function feedTone(status: string | null | undefined): { tone: Tone; label: string } {
  switch (status) {
    case "ok":
      return { tone: "green", label: "fine" };
    case "watch":
      return { tone: "amber", label: "worth a look" };
    case "bad":
      return { tone: "red", label: "needs attention" };
    default:
      return { tone: "neutral", label: "no status" };
  }
}

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

/** "just now", "5 h ago", "3 days ago"; "" without a time. */
export function ago(ms: number, now: number): string {
  if (!ms || !Number.isFinite(ms)) return "";
  const d = Math.max(0, now - ms);
  if (d < 2 * 60_000) return "just now";
  if (d < HOUR) return `${Math.round(d / 60_000)} min ago`;
  if (d < DAY) return `${Math.round(d / HOUR)} h ago`;
  const days = Math.round(d / DAY);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

// ── Home insights ────────────────────────────────────────────────────────────
// The scoring is documented in docs/LAB-FEEDS.md ("How Home picks its three
// insights"); keep the two in step.

export interface Insight {
  /** Which feed it came from; Home shows at most one per source. */
  source: string;
  /** The feed's title: where this comes from, in plain words. */
  title: string;
  text: string;
  detail: string | null;
  status: FeedStatus;
  score: number;
  atMs: number;
  link: string | null;
}

/** Below this an insight is not worth a place on Home. */
export const INSIGHT_FLOOR = 20;
export const HALF_AFTER_MS = 36 * HOUR;
export const GONE_AFTER_MS = 7 * DAY;

/** Full weight for 36 hours, half until a week, nothing after. */
export function decay(score: number, ageMs: number): number {
  if (ageMs > GONE_AFTER_MS) return 0;
  return ageMs > HALF_AFTER_MS ? score / 2 : score;
}

function candidates(feeds: LabFeed[], forward: ForwardReport | null, learn: LearnDigest | null): Insight[] {
  const out: Insight[] = [];
  for (const f of feeds) {
    // The forward report and the learning loop also write the header; when
    // their full reports are here, the plain sentences below stand for them.
    if ((f.name === "forward" && forward) || (f.name === "learn" && learn)) continue;
    for (const it of f.items) {
      if (it.importance == null) continue;
      out.push({
        source: f.name,
        title: f.title,
        text: it.value ? `${it.label}: ${it.value}` : it.label,
        detail: it.detail,
        status: it.status ?? f.status,
        score: it.importance,
        atMs: it.atMs ?? f.updatedMs,
        link: it.link,
      });
    }
    const headline = f.status === "bad" ? 60 : f.status === "watch" ? 35 : 0;
    if (headline > 0 && f.headline) {
      out.push({ source: f.name, title: f.title, text: f.headline, detail: null, status: f.status, score: headline, atMs: f.updatedMs, link: null });
    }
  }
  if (forward) {
    for (const r of [...forward.books, ...forward.autopilots]) {
      const below = r.position === "below";
      if (!below && r.status !== "watch") continue;
      out.push({
        source: "forward",
        title: "Forward tests",
        text: below ? `${r.label || r.name} is below what its backtest expected` : `${r.label || r.name} is worth watching`,
        detail: r.sentence || null,
        status: "watch",
        score: below ? 75 : 40,
        atMs: forward.generatedMs,
        link: null,
      });
    }
  }
  if (learn) {
    for (const d of learn.decisions) {
      const score = d.decision === "promoted" ? 70 : d.decision === "rejected" ? 35 : 0;
      if (!score) continue;
      out.push({
        source: "learn",
        title: "Learning loop",
        text: d.decision === "promoted" ? `A better ${d.model} model is now in use` : `A new ${d.model} model was turned down`,
        detail: d.why || null,
        status: d.decision === "promoted" ? "ok" : "watch",
        score,
        atMs: learn.generatedMs,
        link: null,
      });
    }
  }
  return out;
}

/**
 * The few things from the lab worth knowing today: scored, aged, at most one
 * per feed, best first. Empty when nothing clears the floor, which Home shows
 * as "all quiet".
 */
export function pickInsights(
  feeds: LabFeed[],
  forward: ForwardReport | null,
  learn: LearnDigest | null,
  now: number,
  max = 3,
): Insight[] {
  const scored = candidates(feeds, forward, learn)
    .map((c) => ({ ...c, score: decay(c.score, now - c.atMs) }))
    .filter((c) => c.score > INSIGHT_FLOOR)
    .sort((a, b) => b.score - a.score || b.atMs - a.atMs || a.source.localeCompare(b.source));
  const seen = new Set<string>();
  const out: Insight[] = [];
  for (const c of scored) {
    if (seen.has(c.source)) continue;
    seen.add(c.source);
    out.push(c);
    if (out.length >= max) break;
  }
  return out;
}
