import type {
  JournalEntry,
  JournalKind,
  Market,
  Mode,
  Order,
  PortfolioSnapshot,
  PositionView,
  RiskLimits,
  StrategyConfig,
  VenueBalance,
  Venue,
} from "../types";
import { MarketSim } from "./marketSim";
import { DEFAULT_LIMITS, evaluate, kellySize, type RiskContext } from "./risk";
import { defaultStrategies, runStrategy } from "./strategies";
import type { EngineClient } from "./client";

interface PositionInternal {
  marketId: string;
  venue: Venue;
  symbol: string;
  qty: number;
  avgPrice: number;
}

type Listener = () => void;

const STARTING_CASH = 100_000;

let seq = 0;
const nextId = (p: string) => `${p}_${Date.now().toString(36)}_${(seq++).toString(36)}`;

// The client-side paper engine. It is the reference implementation of Pythia's
// core; the Rust backend mirrors it. Everything here is SIMULATED — no real
// money, no network. Real venues arrive in Phase 1 behind the connector trait.
export class PaperEngine implements EngineClient {
  private sim = new MarketSim();
  private positions = new Map<string, PositionInternal>();
  private orders: Order[] = [];
  private journal: JournalEntry[] = [];
  private strategies: StrategyConfig[] = defaultStrategies();
  private limits: RiskLimits = { ...DEFAULT_LIMITS };
  private cash = STARTING_CASH;
  private realizedPnl = 0;
  private dayStartEquity = STARTING_CASH;
  private equityCurve: number[] = [STARTING_CASH];
  private orderTimestamps: number[] = [];
  private listeners = new Set<Listener>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private tickCount = 0;
  private version = 0;

  constructor() {
    this.log("system", "Pythia paper engine initialized · balance $100,000 (simulated)");
  }

  // ── lifecycle ───────────────────────────────────────────────────────────
  start(intervalMs = 1500) {
    if (this.timer) return;
    this.timer = setInterval(() => this.tick(), intervalMs);
  }
  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }
  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }
  private emit() {
    this.version++;
    for (const l of this.listeners) l();
  }
  /** Monotonic counter — bumps on every state change so the UI always re-renders. */
  getVersion(): number {
    return this.version;
  }

  // ── main loop ─────────────────────────────────────────────────────────────
  private tick() {
    this.tickCount++;
    const markets = this.sim.tick();
    const byId = new Map(markets.map((m) => [m.id, m]));
    // position marks are read live from the sim in the views, so nothing to
    // recompute here beyond advancing prices (done above).

    // run active strategies every few ticks to avoid churn
    if (this.tickCount % 3 === 0) {
      for (const strat of this.strategies) {
        const intents = runStrategy(strat, byId);
        for (const intent of intents) {
          const m = byId.get(intent.marketId);
          if (!m) continue;
          this.log(
            "signal",
            `${strat.name}: ${intent.side.toUpperCase()} ${m.symbol} — ${intent.reason}`,
            strat.id,
            intent.marketId
          );
          this.placeFromIntent(strat, m, intent);
        }
      }
    }

    this.equityCurve.push(this.equity());
    if (this.equityCurve.length > 300) this.equityCurve.shift();
    this.emit();
  }

  private placeFromIntent(
    strat: StrategyConfig,
    m: Market,
    intent: { side: "buy" | "sell"; size: number; confidence: number }
  ) {
    const price = m.price;
    const budget = (strat.budgetPct / 100) * this.equity();
    const kelly = kellySize(intent.confidence, price, budget, this.limits);
    const qtyWanted = Math.max(0, kelly * intent.size);
    if (qtyWanted <= 0) return;

    const mode: Mode = strat.state === "live" ? "live" : "paper";
    const order: Order = {
      id: nextId("ord"),
      ts: Date.now(),
      strategyId: strat.id,
      marketId: m.id,
      venue: m.venue,
      side: intent.side,
      type: "market",
      qty: qtyWanted,
      status: "pending",
      filledQty: 0,
      mode,
    };

    const decision = evaluate(order, price, this.limits, this.riskCtx());
    if (!decision.approved) {
      order.status = "rejected";
      order.rejectReason = decision.reason;
      this.orders.unshift(order);
      this.log("reject", `Rejected ${m.symbol}: ${decision.reason}`, strat.id, m.id);
      return;
    }

    order.qty = decision.qty;
    this.fill(order, price, strat);
  }

  private fill(order: Order, price: number, strat: StrategyConfig) {
    // simulated slippage + fee
    const slip = order.side === "buy" ? 1.0008 : 0.9992;
    const fillPrice = Number((price * slip).toFixed(order.venue === "polymarket" ? 4 : 2));
    const fee = fillPrice * order.qty * 0.0006;

    order.status = "filled";
    order.filledQty = order.qty;
    order.avgFillPrice = fillPrice;
    this.orders.unshift(order);
    this.orderTimestamps.push(Date.now());

    const signed = order.side === "buy" ? order.qty : -order.qty;
    const key = order.marketId;
    const existing = this.positions.get(key);

    if (!existing) {
      this.positions.set(key, {
        marketId: order.marketId,
        venue: order.venue,
        symbol: order.marketId.split(":").slice(1).join(":") || order.marketId,
        qty: signed,
        avgPrice: fillPrice,
      });
    } else {
      const newQty = existing.qty + signed;
      if (Math.sign(newQty) === Math.sign(existing.qty) || existing.qty === 0) {
        // adding to / opening same side: weighted avg
        const totalCost = existing.avgPrice * Math.abs(existing.qty) + fillPrice * Math.abs(signed);
        existing.avgPrice = Math.abs(newQty) > 0 ? totalCost / Math.abs(newQty) : fillPrice;
      } else {
        // reducing/closing: realize P&L on the closed portion
        const closedQty = Math.min(Math.abs(signed), Math.abs(existing.qty));
        const dir = existing.qty > 0 ? 1 : -1;
        const realized = (fillPrice - existing.avgPrice) * closedQty * dir;
        this.realizedPnl += realized;
        strat.pnl += realized;
        strat.trades++;
        strat.winRate =
          (strat.winRate * (strat.trades - 1) + (realized >= 0 ? 1 : 0)) / strat.trades;
      }
      if (Math.abs(newQty) < 1e-9) this.positions.delete(key);
      else existing.qty = newQty;
    }

    this.cash -= signed * fillPrice + fee;
    strat.equityCurve.push(strat.pnl);
    if (strat.equityCurve.length > 200) strat.equityCurve.shift();

    this.log(
      "fill",
      `${order.mode.toUpperCase()} FILL ${order.side} ${order.qty.toFixed(4)} ${order.marketId} @ ${fillPrice}`,
      strat.id,
      order.marketId
    );
  }

  // ── manual order (from the UI) ────────────────────────────────────────────
  manualOrder(marketId: string, side: "buy" | "sell", notional: number): string {
    const m = this.sim.get(marketId);
    if (!m) return "unknown market";
    const qty = notional / m.price;
    const order: Order = {
      id: nextId("ord"),
      ts: Date.now(),
      strategyId: "manual",
      marketId,
      venue: m.venue,
      side,
      type: "market",
      qty,
      status: "pending",
      filledQty: 0,
      mode: "paper",
    };
    const decision = evaluate(order, m.price, this.limits, this.riskCtx());
    if (!decision.approved) {
      order.status = "rejected";
      order.rejectReason = decision.reason;
      this.orders.unshift(order);
      this.log("reject", `Manual order rejected: ${decision.reason}`, "manual", marketId);
      this.emit();
      return decision.reason ?? "rejected";
    }
    order.qty = decision.qty;
    const manualStrat: StrategyConfig = {
      id: "manual",
      name: "Manual",
      kind: "manual",
      venueClass: m.venue,
      state: "paper",
      universe: [],
      params: [],
      budgetPct: 100,
      pnl: 0,
      trades: 0,
      winRate: 0,
      equityCurve: [0],
    };
    this.fill(order, m.price, manualStrat);
    this.emit();
    return "ok";
  }

  flatten(marketId: string) {
    const p = this.positions.get(marketId);
    if (!p) return;
    const m = this.sim.get(marketId);
    if (!m) return;
    const side = p.qty > 0 ? "sell" : "buy";
    const order: Order = {
      id: nextId("ord"),
      ts: Date.now(),
      strategyId: "manual",
      marketId,
      venue: p.venue,
      side,
      type: "market",
      qty: Math.abs(p.qty),
      status: "pending",
      filledQty: 0,
      mode: "paper",
    };
    const strat: StrategyConfig = {
      id: "manual", name: "Manual", kind: "manual", venueClass: p.venue,
      state: "paper", universe: [], params: [], budgetPct: 100,
      pnl: 0, trades: 0, winRate: 0, equityCurve: [0],
    };
    this.fill(order, m.price, strat);
    this.log("system", `Flattened ${marketId}`, "manual", marketId);
    this.emit();
  }

  // ── risk context ──────────────────────────────────────────────────────────
  private riskCtx(): RiskContext {
    return {
      equity: this.equity(),
      dayStartEquity: this.dayStartEquity,
      realizedPnl: this.realizedPnl,
      unrealizedPnl: this.unrealized(),
      grossExposure: this.grossExposure(),
      positionNotional: (id) => {
        const p = this.positions.get(id);
        const m = this.sim.get(id);
        return p && m ? p.qty * m.price : 0;
      },
      ordersLastMin: (sid) => {
        const cutoff = Date.now() - 60_000;
        return this.orders.filter((o) => o.strategyId === sid && o.ts > cutoff).length;
      },
      strategyExposure: (sid) => {
        // Approximate a strategy's deployed capital from its fills in the last
        // minute (a full engine tracks lot ownership per strategy; the Rust
        // core does exactly that).
        const cutoff = Date.now() - 60_000;
        return this.orders
          .filter((o) => o.strategyId === sid && o.status === "filled" && o.ts > cutoff)
          .reduce((acc, o) => acc + (o.avgFillPrice ?? 0) * o.filledQty, 0);
      },
      dataAgeSec: (id) => {
        const m = this.sim.get(id);
        return m ? (Date.now() - m.updatedAt) / 1000 : 999;
      },
    };
  }

  // ── derived values ────────────────────────────────────────────────────────
  private unrealized(): number {
    let u = 0;
    for (const p of this.positions.values()) {
      const m = this.sim.get(p.marketId);
      if (m) u += (m.price - p.avgPrice) * p.qty;
    }
    return u;
  }
  private grossExposure(): number {
    let g = 0;
    for (const p of this.positions.values()) {
      const m = this.sim.get(p.marketId);
      if (m) g += Math.abs(p.qty * m.price);
    }
    return g;
  }
  private equity(): number {
    return this.cash + this.positionsValue();
  }
  private positionsValue(): number {
    let v = 0;
    for (const p of this.positions.values()) {
      const m = this.sim.get(p.marketId);
      if (m) v += p.qty * m.price;
    }
    return v;
  }

  // ── public read API (consumed by the store) ────────────────────────────────
  snapshot(): PortfolioSnapshot {
    const balances: VenueBalance[] = (["polymarket", "crypto", "alpaca"] as Venue[]).map(
      (venue) => ({
        venue,
        connected: false, // no live keys in paper mode
        cash: this.cash / 3,
        equity: this.equity() / 3,
        mode: "paper" as Mode,
      })
    );
    return {
      mode: this.anyLive() ? "live" : "paper",
      cash: this.cash,
      equity: this.equity(),
      dayStartEquity: this.dayStartEquity,
      realizedPnl: this.realizedPnl,
      unrealizedPnl: this.unrealized(),
      grossExposure: this.grossExposure(),
      equityCurve: [...this.equityCurve],
      balances,
    };
  }

  anyLive(): boolean {
    return this.strategies.some((s) => s.state === "live");
  }

  markets(): Market[] {
    return this.sim.list();
  }
  positionViews(): PositionView[] {
    const out: PositionView[] = [];
    for (const p of this.positions.values()) {
      const m = this.sim.get(p.marketId);
      if (!m) continue;
      out.push({
        marketId: p.marketId,
        venue: p.venue,
        symbol: m.symbol,
        qty: p.qty,
        avgPrice: p.avgPrice,
        lastPrice: m.price,
        unrealized: (m.price - p.avgPrice) * p.qty,
        mode: "paper",
      });
    }
    return out;
  }
  orderList(): Order[] {
    return this.orders.slice(0, 200);
  }
  journalList(): JournalEntry[] {
    return this.journal.slice(0, 400);
  }
  strategyList(): StrategyConfig[] {
    return this.strategies.map((s) => ({ ...s }));
  }
  getLimits(): RiskLimits {
    return { ...this.limits };
  }

  // ── mutations from the UI ──────────────────────────────────────────────────
  setLimits(next: Partial<RiskLimits>) {
    this.limits = { ...this.limits, ...next };
    this.log("risk", `Risk limits updated${next.killSwitch !== undefined ? ` · kill switch ${next.killSwitch ? "ON" : "OFF"}` : ""}`);
    this.emit();
  }
  toggleKill() {
    this.limits.killSwitch = !this.limits.killSwitch;
    this.log("risk", `KILL SWITCH ${this.limits.killSwitch ? "ENGAGED — live buys halted" : "released"}`);
    this.emit();
  }
  setStrategyState(id: string, state: StrategyConfig["state"]) {
    const s = this.strategies.find((x) => x.id === id);
    if (!s) return;
    s.state = state;
    this.log("system", `Strategy ${s.name} → ${state.toUpperCase()}`, id);
    this.emit();
  }
  setStrategyParam(id: string, key: string, value: number) {
    const s = this.strategies.find((x) => x.id === id);
    const p = s?.params.find((x) => x.key === key);
    if (p) {
      p.value = value;
      this.emit();
    }
  }

  private log(kind: JournalKind, message: string, strategyId?: string, marketId?: string) {
    this.journal.unshift({
      id: nextId("j"),
      ts: Date.now(),
      kind,
      strategyId,
      marketId,
      message,
      mode: this.anyLive() ? "live" : "paper",
    });
    if (this.journal.length > 1000) this.journal.pop();
  }
}
