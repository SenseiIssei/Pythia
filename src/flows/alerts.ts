// The notifications center: what GET /api/alerts reports, in plain words, and
// the calls behind its buttons. Only the Pythia server sends alerts; the
// desktop app and the browser demo say so instead.

import { serverUrl } from "../engine/serverEngine";
import type { JournalEntry } from "../types";

export type AlertKind =
  | "autopilotStarted"
  | "autopilotStopped"
  | "stopRuleHit"
  | "floorHit"
  | "killSwitch"
  | "dailyLossBrake"
  | "orderRejects"
  | "reconcileMismatch"
  | "dataStale"
  | "modelDrift"
  | "trade"
  | "bigMove"
  | "event"
  | "overnight"
  | "test";

/** Mirrors Rust `alerts::AlertRecord`. */
export interface AlertRecord {
  ts: number;
  kinds: AlertKind[];
  /** The first card's title, plain text. */
  title?: string;
  /** What was posted, in the destination's markup (HTML for Telegram). */
  text: string;
  delivered: boolean;
  error: string | null;
  /** Why nothing was posted: "muted", "quiet" or "hourlyLimit". */
  reason?: string;
  /** A chart went with it as a photo. */
  photo?: boolean;
}

export interface AlertCounts {
  sentToday: number;
  failedToday: number;
  suppressedToday: number;
}

/** GET /api/alerts. */
export interface AlertsView {
  enabled: boolean;
  destination: string | null;
  mutedUntilMs: number;
  counts: AlertCounts;
  recent: AlertRecord[];
  lastDigest: { ts: number; text: string } | null;
}

/** Same words as the engine's `AlertKind::label`, a little plainer. */
export const KIND_LABEL: Record<AlertKind, string> = {
  autopilotStarted: "Autopilot started",
  autopilotStopped: "Autopilot stopped",
  stopRuleHit: "Stop rule reached",
  floorHit: "Loss limit reached",
  killSwitch: "Kill switch",
  dailyLossBrake: "Daily loss brake",
  orderRejects: "Orders refused",
  reconcileMismatch: "Balances do not match",
  dataStale: "Prices are late",
  modelDrift: "Model drift",
  trade: "Trade",
  bigMove: "Big move",
  event: "From the lab",
  overnight: "Quiet hours are over",
  test: "Test message",
};

/** The title of one alert: its card's title, else its first kind; plus how many more. */
export function alertTitle(a: Pick<AlertRecord, "kinds"> & { title?: string }): string {
  if (a.kinds.length === 0) return a.title || "Alert";
  const first = a.title || (KIND_LABEL[a.kinds[0]] ?? a.kinds[0]);
  return a.kinds.length > 1 ? `${first} +${a.kinds.length - 1}` : first;
}

/** A post without its markup: Telegram HTML tags and entities, markdown stars and fences. */
export function plainText(text: string): string {
  return text
    .replace(/<[^>]+>/g, "")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/```/g, "")
    .replace(/\*\*/g, "");
}

export type DeliveryTone = "good" | "warn" | "bad" | "neutral";

/** Delivered, failed, muted or held back, in words. */
export function deliveryOf(a: Pick<AlertRecord, "delivered" | "error" | "reason">): { label: string; tone: DeliveryTone } {
  if (a.delivered) return { label: "Delivered", tone: "good" };
  if (a.reason === "muted") return { label: "Muted", tone: "neutral" };
  if (a.reason === "quiet") return { label: "Quiet hours", tone: "neutral" };
  if (a.reason === "hourlyLimit") return { label: "Held back", tone: "warn" };
  return { label: a.error ? `Failed: ${a.error}` : "Failed", tone: "bad" };
}

/** "Muted for 45 min", "Muted for 3 h", "Muted until Mon 14:00", or null when not muted. */
export function muteText(mutedUntilMs: number, now: number): string | null {
  if (!(mutedUntilMs > now)) return null;
  const min = Math.ceil((mutedUntilMs - now) / 60_000);
  if (min < 60) return `Muted for ${min} min`;
  const h = Math.round(min / 60);
  if (h < 24) return `Muted for ${h} h`;
  const when = new Date(mutedUntilMs).toLocaleString("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit" });
  return `Muted until ${when}`;
}

export const MUTE_CHOICES: { minutes: number; label: string }[] = [
  { minutes: 60, label: "1 hour" },
  { minutes: 8 * 60, label: "8 hours" },
  { minutes: 24 * 60, label: "1 day" },
];

/** Where alerts go, by name. */
export function destinationName(d: string | null | undefined): string {
  switch (d) {
    case "discord":
      return "Discord";
    case "slack":
      return "Slack";
    case "telegram":
      return "Telegram";
    default:
      return d ? d : "nowhere";
  }
}

/** Counts in one short line: "4 sent today · 1 failed · 2 held back". */
export function countsLine(c: AlertCounts | null | undefined): string {
  if (!c) return "";
  const parts = [`${c.sentToday} sent today`];
  if (c.failedToday) parts.push(`${c.failedToday} failed`);
  if (c.suppressedToday) parts.push(`${c.suppressedToday} held back`);
  return parts.join(" · ");
}

/** A server answer, or the reason there is none. */
export type Fetched<T> = { ok: true; data: T } | { ok: false; error: string };

/** True when this build talks to the Pythia server, which is what sends alerts. */
export function alertsAvailable(): boolean {
  return serverUrl() != null;
}

async function readError(r: Response): Promise<string> {
  try {
    const t = await r.text();
    try {
      const j = JSON.parse(t) as { error?: string };
      if (j && typeof j.error === "string") return j.error;
    } catch {
      /* plain text */
    }
    return t.trim() || `HTTP ${r.status}`;
  } catch {
    return `HTTP ${r.status}`;
  }
}

export async function fetchAlerts(): Promise<Fetched<AlertsView>> {
  const base = serverUrl();
  if (!base) return { ok: false, error: "Notifications need the Pythia server." };
  try {
    const r = await fetch(`${base}/api/alerts`);
    if (!r.ok) return { ok: false, error: await readError(r) };
    return { ok: true, data: (await r.json()) as AlertsView };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function sendTest(): Promise<Fetched<AlertRecord>> {
  const base = serverUrl();
  if (!base) return { ok: false, error: "Notifications need the Pythia server." };
  try {
    const r = await fetch(`${base}/api/alerts/test`, { method: "POST" });
    if (r.status === 200) return { ok: true, data: (await r.json()) as AlertRecord };
    if (r.status === 502) {
      const rec = (await r.json()) as AlertRecord;
      return { ok: false, error: rec.error ? `Not delivered: ${rec.error}` : "Not delivered." };
    }
    return { ok: false, error: await readError(r) };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

/** 0 unmutes. */
export async function setMute(minutes: number): Promise<Fetched<{ mutedUntilMs: number }>> {
  const base = serverUrl();
  if (!base) return { ok: false, error: "Notifications need the Pythia server." };
  try {
    const r = await fetch(`${base}/api/alerts/mute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ minutes }),
    });
    if (!r.ok) return { ok: false, error: await readError(r) };
    return { ok: true, data: (await r.json()) as { mutedUntilMs: number } };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

// ── settings: what is sent, and when ─────────────────────────────────────────

export type AlertCategoryId =
  | "trades"
  | "rebalances"
  | "dailyPnl"
  | "bigMoves"
  | "autopilot"
  | "risk"
  | "venue"
  | "models"
  | "studies"
  | "listings"
  | "trending"
  | "cs2"
  | "pokemon"
  | "weekly";

/** One switch, as GET /api/alerts/settings lists it. */
export interface AlertCategoryView {
  id: AlertCategoryId;
  label: string;
  emoji: string;
  about: string;
  /** Who sends it: the engine itself, or a lab job. */
  source: "engine" | "lab";
  on: boolean;
}

export interface QuietHours {
  enabled: boolean;
  /** HH:MM local time in `timezone`. */
  start: string;
  end: string;
  timezone: string;
}

export interface BigMoves {
  hourPct: number;
  dayPct: number;
}

/** GET /api/alerts/settings (and what POST answers). */
export interface AlertSettingsView {
  categories: AlertCategoryView[];
  quietHours: QuietHours;
  bigMoves: BigMoves;
  quietNow: boolean;
}

/** A change: what is left out stays. */
export interface AlertSettingsPatch {
  categories?: Partial<Record<AlertCategoryId, boolean>>;
  quietHours?: Partial<QuietHours>;
  bigMoves?: Partial<BigMoves>;
}

/** Whether a time is HH:MM, 00:00 to 23:59. */
export function validHhmm(s: string): boolean {
  const m = /^(\d{1,2}):(\d{2})$/.exec(s.trim());
  return !!m && Number(m[1]) < 24 && Number(m[2]) < 60;
}

/** "23:00 to 07:00", or "Off". */
export function quietLine(q: QuietHours | null | undefined): string {
  if (!q || !q.enabled) return "Off";
  return `${q.start} to ${q.end}`;
}

/** The switches split by who sends them, engine first. */
export function groupCategories(cats: AlertCategoryView[]): { engine: AlertCategoryView[]; lab: AlertCategoryView[] } {
  return { engine: cats.filter((c) => c.source === "engine"), lab: cats.filter((c) => c.source !== "engine") };
}

export async function fetchSettings(): Promise<Fetched<AlertSettingsView>> {
  const base = serverUrl();
  if (!base) return { ok: false, error: "Notifications need the Pythia server." };
  try {
    const r = await fetch(`${base}/api/alerts/settings`);
    if (!r.ok) return { ok: false, error: await readError(r) };
    return { ok: true, data: (await r.json()) as AlertSettingsView };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export async function saveSettings(patch: AlertSettingsPatch): Promise<Fetched<AlertSettingsView>> {
  const base = serverUrl();
  if (!base) return { ok: false, error: "Notifications need the Pythia server." };
  try {
    const r = await fetch(`${base}/api/alerts/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!r.ok) return { ok: false, error: await readError(r) };
    return { ok: true, data: (await r.json()) as AlertSettingsView };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

/** The engine's events ring, from GET /api/state (not in the stream). */
export async function fetchEvents(): Promise<Fetched<JournalEntry[]>> {
  const base = serverUrl();
  if (!base) return { ok: false, error: "no server" };
  try {
    const r = await fetch(`${base}/api/state`);
    if (!r.ok) return { ok: false, error: await readError(r) };
    const s = (await r.json()) as { events?: JournalEntry[] };
    return { ok: true, data: s.events ?? [] };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}
