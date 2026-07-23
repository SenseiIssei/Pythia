import type {
  JournalEntry,
  Market,
  Order,
  PortfolioSnapshot,
  PositionView,
  RiskLimits,
  Side,
  StrategyConfig,
  StrategyState,
} from "../types";
import { DISARMED, type EngineClient, type EngineState } from "./client";
import { DEFAULT_LIMITS } from "./risk";

const EMPTY: EngineState = {
  portfolio: {
    mode: "paper",
    cash: 0,
    equity: 0,
    dayStartEquity: 0,
    realizedPnl: 0,
    unrealizedPnl: 0,
    grossExposure: 0,
    equityCurve: [],
    balances: [],
  },
  markets: [],
  positions: [],
  orders: [],
  journal: [],
  strategies: [],
  limits: DEFAULT_LIMITS,
  history: {},
  live: DISARMED,
};

/**
 * Talks to the standalone `pythia-server` backend over the network — the same
 * engine the desktop app runs, reached via HTTP + WebSocket instead of Tauri
 * IPC. This is the path for a web dashboard or a phone app: one authoritative
 * brain, many front-ends.
 *
 * State arrives over `GET /api/stream` (WebSocket, pushed every tick); mutations
 * go out as `POST /api/command`. Auto-reconnects with backoff so a backend
 * restart doesn't kill the UI.
 */
export class ServerEngineClient implements EngineClient {
  private state: EngineState = EMPTY;
  private listeners = new Set<() => void>();
  private version = 0;
  private ws: WebSocket | null = null;
  private started = false;
  private closed = false;
  private backoff = 1000;
  private readonly http: string; // e.g. http://localhost:8787
  private readonly wsUrl: string; // e.g. ws://localhost:8787/api/stream

  constructor(baseUrl: string) {
    this.http = baseUrl.replace(/\/$/, "");
    this.wsUrl = this.http.replace(/^http/, "ws") + "/api/stream";
  }

  start() {
    if (this.started) return;
    this.started = true;
    this.closed = false;
    this.connect();
  }

  stop() {
    this.closed = true;
    this.ws?.close();
    this.ws = null;
  }

  private connect() {
    if (this.closed) return;
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.wsUrl);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onmessage = (ev) => {
      try {
        this.state = JSON.parse(ev.data as string) as EngineState;
        this.bump();
      } catch {
        /* ignore malformed frame */
      }
    };
    ws.onopen = () => {
      this.backoff = 1000; // reset backoff on a good connection
    };
    ws.onclose = () => {
      if (this.ws === ws) this.ws = null;
      this.scheduleReconnect();
    };
    ws.onerror = () => {
      ws.close(); // triggers onclose → reconnect
    };
  }

  private scheduleReconnect() {
    if (this.closed) return;
    const delay = this.backoff;
    this.backoff = Math.min(this.backoff * 2, 15000);
    setTimeout(() => this.connect(), delay);
  }

  subscribe(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }
  private bump() {
    this.version++;
    for (const l of this.listeners) l();
  }
  getVersion(): number {
    return this.version;
  }

  snapshot(): PortfolioSnapshot {
    return this.state.portfolio;
  }
  markets(): Market[] {
    return this.state.markets;
  }
  positionViews(): PositionView[] {
    return this.state.positions;
  }
  orderList(): Order[] {
    return this.state.orders;
  }
  journalList(): JournalEntry[] {
    return this.state.journal;
  }
  strategyList(): StrategyConfig[] {
    return this.state.strategies;
  }
  getLimits(): RiskLimits {
    return this.state.limits;
  }
  history(): Record<string, number[]> {
    return this.state.history ?? {};
  }
  liveStatus() {
    return this.state.live ?? DISARMED;
  }

  /** POST a command; the response carries fresh state so the UI updates now. */
  private send(body: Record<string, unknown>) {
    void fetch(this.http + "/api/command", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((s: EngineState | null) => {
        if (s) {
          this.state = s;
          this.bump();
        }
      })
      .catch(() => {
        /* the WebSocket will resync on the next tick */
      });
  }

  toggleKill() {
    this.send({ cmd: "toggleKill" });
  }
  setLimits(l: Partial<RiskLimits>) {
    this.send({ cmd: "setLimits", patch: { ...this.state.limits, ...l } });
  }
  setStrategyState(id: string, s: StrategyState) {
    this.send({ cmd: "setStrategyState", id, state: s });
  }
  setStrategyParam(id: string, key: string, value: number) {
    this.send({ cmd: "setStrategyParam", id, key, value });
  }
  addStrategy(cfg: StrategyConfig) {
    this.send({ cmd: "addStrategy", cfg });
  }
  manualOrder(marketId: string, side: Side, notional: number): string {
    this.send({ cmd: "manualOrder", marketId, side, notional });
    return "ok"; // rejections surface in the journal pushed back over the stream
  }
  flatten(marketId: string) {
    this.send({ cmd: "flatten", marketId });
  }
}

/**
 * The backend URL, if the app was built to talk to one. Set `VITE_PYTHIA_SERVER`
 * (e.g. `http://localhost:8787`) at build/dev time to make the browser build a
 * thin client of the standalone backend instead of running its own paper engine.
 */
export function serverUrl(): string | null {
  const env = (import.meta as unknown as { env?: Record<string, string> }).env;
  const url = env?.VITE_PYTHIA_SERVER?.trim();
  return url ? url : null;
}
