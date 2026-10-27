// Lab Live (GET /api/lab/live): one graph of everything that runs in the lab,
// built every 5 minutes by the lab job `lablive` (research/lab/lab/ops/lablive.py)
// from the job table, the run records and the reports. The page draws it as a
// map in columns, from the data to the models, the books and the money. Read
// only: nothing here trades or changes a setting.

import { liveMode } from "./live";
import { serverUrl } from "./engine/serverEngine";
import { openPage } from "./navigate";

export const COLUMNS = ["data", "features", "models", "factories", "books", "money", "outputs"] as const;
export type Column = (typeof COLUMNS)[number];
export const STATES = ["running", "ok", "late", "failed", "off"] as const;
export type NodeState = (typeof STATES)[number];

export const LIVE_POLL_MS = 30_000;

export const COLUMN_LABEL: Record<Column, string> = {
  data: "Daten",
  features: "Merkmale",
  models: "Modelle",
  factories: "Fabriken und Studien",
  books: "Paper-Bücher",
  money: "Echtes Geld",
  outputs: "Berichte und Betrieb",
};

export const STATE_LABEL: Record<NodeState, string> = {
  running: "läuft gerade",
  ok: "in Ordnung",
  late: "verspätet",
  failed: "fehlgeschlagen",
  off: "aus",
};

/** The colour of a state, from the theme's variables (light and dark). */
export const STATE_COLOR: Record<NodeState, string> = {
  running: "var(--color-accent)",
  ok: "var(--color-up)",
  late: "var(--color-warn)",
  failed: "var(--color-down)",
  off: "var(--color-faint)",
};

export interface NumberRow {
  label: string;
  value: string;
}

export interface Run {
  start: string | null;
  end: string | null;
  status: string | null;
  durationS: number | null;
}

export interface LiveNode {
  id: string;
  kind: string;
  name: string;
  column: Column;
  what: string;
  detail: string;
  state: NodeState;
  now: string;
  lastRun: string | null;
  nextRun: string | null;
  numbers: NumberRow[];
  spark: number[];
  sparkLabel: string;
  runs: Run[];
  logs: string[];
  inputs: string[];
  outputs: string[];
  schedule: string | null;
}

export interface LiveEdge {
  from: string;
  to: string;
}

export interface LiveGraph {
  found: boolean;
  updatedMs: number | null;
  nodes: LiveNode[];
  edges: LiveEdge[];
  counts: Record<NodeState, number>;
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const strOrNull = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
const obj = (v: unknown): Record<string, unknown> => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

function parseNode(r: unknown): LiveNode | null {
  const o = obj(r);
  const id = str(o.id);
  if (!id) return null;
  const column = (COLUMNS as readonly string[]).includes(str(o.column)) ? (o.column as Column) : "outputs";
  const state = (STATES as readonly string[]).includes(str(o.state)) ? (o.state as NodeState) : "ok";
  return {
    id,
    kind: str(o.kind) || "job",
    name: str(o.name) || id,
    column,
    what: str(o.what),
    detail: str(o.detail),
    state,
    now: str(o.now),
    lastRun: strOrNull(o.last_run),
    nextRun: strOrNull(o.next_run),
    numbers: arr(o.numbers)
      .map(obj)
      .filter((x) => str(x.label))
      .map((x) => ({ label: str(x.label), value: str(x.value) || "-" })),
    spark: arr(o.spark).map(num).filter((x): x is number => x != null),
    sparkLabel: str(o.spark_label),
    runs: arr(o.runs)
      .map(obj)
      .map((x) => ({ start: strOrNull(x.start), end: strOrNull(x.end), status: strOrNull(x.status), durationS: num(x.duration_s) })),
    logs: strs(o.logs),
    inputs: strs(o.inputs),
    outputs: strs(o.outputs),
    schedule: strOrNull(o.schedule),
  };
}

export function parseLive(raw: unknown): LiveGraph {
  const o = obj(raw);
  const nodes = arr(o.nodes).map(parseNode).filter((n): n is LiveNode => n != null);
  const ids = new Set(nodes.map((n) => n.id));
  const edges = arr(o.edges)
    .map(obj)
    .map((e) => ({ from: str(e.from), to: str(e.to) }))
    .filter((e) => ids.has(e.from) && ids.has(e.to));
  const counts = Object.fromEntries(STATES.map((s) => [s, nodes.filter((n) => n.state === s).length])) as Record<NodeState, number>;
  return { found: o.found === true, updatedMs: num(o.updated_ms), nodes, edges, counts };
}

export function canReadLive(): boolean {
  return liveMode() === "server";
}

/** GET only: the page never sends anything else. */
export async function fetchLive(): Promise<LiveGraph> {
  if (!canReadLive()) throw new Error("Lab Live braucht den Server.");
  const r = await fetch(`${serverUrl()}/api/lab/live`, { method: "GET", cache: "no-store" });
  if (!r.ok) throw new Error(`Der Server antwortete ${r.status}`);
  return parseLive(await r.json());
}

// ── the map ──

export const MAP = { colW: 210, nodeW: 180, nodeH: 30, rowH: 38, top: 44, pad: 14 } as const;

export interface Placed {
  node: LiveNode;
  x: number;
  y: number;
}

export interface Layout {
  width: number;
  height: number;
  placed: Map<string, Placed>;
  columns: { id: Column; x: number; count: number }[];
}

/** Columns left to right, the nodes of a column top to bottom in the file's order; `hideOff` leaves out what is off. */
export function layout(g: LiveGraph, hideOff = false): Layout {
  const placed = new Map<string, Placed>();
  const columns: Layout["columns"] = [];
  let rows = 0;
  COLUMNS.forEach((c, i) => {
    const x = MAP.pad + i * MAP.colW;
    const ns = g.nodes.filter((n) => n.column === c && !(hideOff && n.state === "off"));
    ns.forEach((node, j) => placed.set(node.id, { node, x, y: MAP.top + j * MAP.rowH }));
    columns.push({ id: c, x, count: ns.length });
    rows = Math.max(rows, ns.length);
  });
  return { width: MAP.pad * 2 + COLUMNS.length * MAP.colW - (MAP.colW - MAP.nodeW), height: MAP.top + rows * MAP.rowH + MAP.pad, placed, columns };
}

/** The curve of an edge: from the right side of its source to the left side of its target. */
export function edgePath(a: Placed, b: Placed): string {
  const x1 = a.x + MAP.nodeW;
  const y1 = a.y + MAP.nodeH / 2;
  const x2 = b.x;
  const y2 = b.y + MAP.nodeH / 2;
  if (x2 > x1) {
    const dx = (x2 - x1) / 2;
    return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
  }
  // Same column or backwards: a loop out to the right and back in from the left.
  const out = 26;
  return `M${x1},${y1} C${x1 + out},${y1} ${x2 - out},${y2} ${x2},${y2}`;
}

/** The edges that carry a pulse: their source runs right now. */
export function pulsing(g: LiveGraph): LiveEdge[] {
  const running = new Set(g.nodes.filter((n) => n.state === "running").map((n) => n.id));
  return g.edges.filter((e) => running.has(e.from));
}

export function neighbours(g: LiveGraph, id: string): Set<string> {
  const s = new Set<string>([id]);
  for (const e of g.edges) {
    if (e.from === id) s.add(e.to);
    if (e.to === id) s.add(e.from);
  }
  return s;
}

/** "27.10. 13:05 UTC" of an ISO time, "-" without one. */
export function whenText(iso: string | null): string {
  if (!iso) return "-";
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
  return m ? `${m[3]}.${m[2]}. ${m[4]}:${m[5]} UTC` : iso;
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
}

// ── opening Lab Live on one node from another page ──

const NODE_EVENT = "pythia:lablive-node";
let pendingNode: string | null = null;

/** Lab Live on `id`: remembered for the page, then the page is opened. */
export function openLabLiveNode(id: string): void {
  pendingNode = id;
  window.dispatchEvent(new CustomEvent<string>(NODE_EVENT, { detail: id }));
  openPage("lablive");
}

/** The node another page asked for, once. */
export function takePendingNode(): string | null {
  const id = pendingNode;
  pendingNode = null;
  return id;
}

export function onNodeRequest(fn: (id: string) => void): () => void {
  const h = (e: Event) => {
    pendingNode = null;
    fn((e as CustomEvent<string>).detail);
  };
  window.addEventListener(NODE_EVENT, h);
  return () => window.removeEventListener(NODE_EVENT, h);
}

/** The `node` (or `article`) the URL names, if any. */
export function queryParam(search: string, name: string): string | null {
  const v = new URLSearchParams(search).get(name);
  return v && /^[\w.:-]{1,200}$/.test(v) ? v : null;
}
