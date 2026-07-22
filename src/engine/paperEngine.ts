import type {
  JournalEntry,
  JournalKind,
  Market,
  Mode,
  Order,
  PortfolioSnapshot,
  PositionView,
  Regime,
  RiskLimits,
  StrategyConfig,
  StrategyKind,
  VenueBalance,
  Venue,
} from "../types";
import { MarketSim } from "./marketSim";
import { DEFAULT_LIMITS, evaluate, kellySize, type RiskContext } from "./risk";
import { defaultStrategies, runStrategy } from "./strategies";
import * as ind from "./indicators";
import type { EngineClient } from "./client";

interface PositionInternal {
  marketId: string;
  venue: Venue;
  symbol: string;
  qty: number;
  avgPrice: number;
  strategyId: string;
  stop: number; // 0 = none
  target: number; // 0 = none
  trailRef: number;
}

type Listener = () => void;

const STARTING_CASH = 100_000;

// Regime filter: mean-reversion blocked in trends; trend strategies blocked in chop.
function strategyRegimeOk(kind: StrategyKind, regime?: Regime): boolean {
  if (regime === "trending" && (kind === "bollinger" || kind === "rsi-reversal")) return false;
  if (regime === "ranging" && (kind === "ema-cross" || kind === "macd-trend" || kind === "breakout" || kind === "multi-tf")) return false;
  return true;
}

let seq = 0;
const nextId = (p: string) => `${p}_${Date.now().toString(36)}_${(seq++).toString(36)}`;

// The client-side paper engine — a 1:1 mirror of the Rust engine core. Every
// number here is SIMULATED (no real money, no network). Under the Tauri shell
// the identical Rust daemon answers instead.
export class PaperEngine implements EngineClient {
  private sim = new MarketSim();
  private history = new Map<string, number[]>();
  private positions = new Map<string, PositionInternal>();
  private orders: Order[] = [];
  private journal: JournalEntry[] = [];
  private strategies: StrategyConfig[] = defaultStrategies();
  private limits: RiskLimits = { ...DEFAULT_LIMITS };
  private cash = STARTING_CASH;
  private realizedPnl = 0;
  private dayStartEquity = STARTING_CASH;
  private peakEquity = STARTING_CASH;
  private day = Math.floor(Date.now() / 86_400_000);
  private equityCurve: number[] = [STARTING_CASH];
  private consecLosses = new Map<string, number>();
  private cooldownUntil = new Map<string, number>();
  private grossWin = new Map<string, number>();
  private grossLoss = new Map<string, number>();
  private listeners = new Set<Listener>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private tickCount = 0;
  private version = 0;

  constructor() {
    for (const m of this.sim.list()) this.history.set(m.id, [m.price]);
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
  getVersion(): number {
    return this.version;
  }

  // ── main loop ─────────────────────────────────────────────────────────────
  private tick() {
    this.tickCount++;
    const now = Date.now();
    const markets = this.sim.tick();
    const byId = new Map(markets.map((m) => [m.id, m]));

    // append each new close to the rolling history
    for (const m of markets) {
      let h = this.history.get(m.id);
      if (!h) {
        h = [];
        this.history.set(m.id, h);
      }
      h.push(m.price);
      if (h.length > 260) h.splice(0, h.length - 260);
    }

    // probability model for prediction markets: an EWMA "fair value" heuristic
    // (NOT a real forecast) so Prob-Edge has a live signal on real Polymarket odds
    for (const m of markets) {
      if (m.kind !== "prediction") continue;
      const h = this.history.get(m.id);
      if (!h) continue;
      const fair = ind.ema(h, 20);
      if (fair !== null) m.modelProb = Math.min(0.98, Math.max(0.02, fair));
    }

    // regime detection for tradable markets (Kaufman efficiency ratio)
    for (const m of markets) {
      if (m.kind === "prediction") continue;
      const h = this.history.get(m.id);
      if (!h) continue;
      const er = ind.efficiencyRatio(h, 20);
      if (er !== null) {
        m.trendStrength = er;
        m.regime = er >= 0.4 ? "trending" : "ranging";
      }
    }

    // daily reset of loss/streak counters
    const today = Math.floor(now / 86_400_000);
    if (today !== this.day) {
      this.day = today;
      this.dayStartEquity = this.equity();
      this.peakEquity = this.dayStartEquity;
      this.consecLosses.clear();
      this.cooldownUntil.clear();
      this.log("system", "New UTC day — daily loss & streak counters reset");
    }

    // stop-loss / take-profit / trailing exits
    this.checkPositionExits();

    // max-drawdown circuit breaker
    const eq = this.equity();
    if (eq > this.peakEquity) this.peakEquity = eq;
    if (this.limits.maxDrawdownPct > 0 && !this.limits.killSwitch && this.peakEquity > 0) {
      const dd = ((this.peakEquity - eq) / this.peakEquity) * 100;
      if (dd >= this.limits.maxDrawdownPct) {
        this.limits.killSwitch = true;
        this.log("risk", `Max drawdown ${dd.toFixed(1)}% ≥ ${this.limits.maxDrawdownPct.toFixed(1)}% — KILL SWITCH tripped`);
      }
    }

    // run strategies every 3rd tick (skip any in cooldown)
    if (this.tickCount % 3 === 0) {
      for (const strat of this.strategies) {
        const until = this.cooldownUntil.get(strat.id);
        if (until && now < until) continue;
        for (const intent of runStrategy(strat, byId, this.history)) {
          const m = byId.get(intent.marketId);
          if (!m) continue;
          if (this.limits.regimeFilter && !strategyRegimeOk(strat.kind, m.regime)) continue;
          this.log("signal", `${strat.name}: ${intent.side.toUpperCase()} ${m.symbol} — ${intent.reason}`, strat.id, intent.marketId);
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
    let qtyWanted = Math.max(0, kelly * intent.size);
    if (this.limits.volTargetPct > 0) {
      const h = this.history.get(m.id);
      const vol = h ? ind.retVol(h, 20) : null;
      if (vol && vol > 0) {
        qtyWanted *= Math.max(0.25, Math.min(3, this.limits.volTargetPct / 100 / vol));
      }
    }
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

  private computeStops(m: Market, side: "buy" | "sell", entry: number): { stop: number; target: number } {
    if (m.kind === "prediction") return { stop: 0, target: 0 };
    const atr = ind.atrProxy(this.history.get(m.id) ?? [], 14);
    if (atr === null || atr <= 0) return { stop: 0, target: 0 };
    const { stopAtrMult: sl, takeProfitAtrMult: tp } = this.limits;
    const long = side === "buy";
    const stop = sl > 0 ? (long ? entry - sl * atr : entry + sl * atr) : 0;
    const target = tp > 0 ? (long ? entry + tp * atr : entry - tp * atr) : 0;
    return { stop, target };
  }

  private fill(order: Order, price: number, strat: StrategyConfig) {
    const slip = order.side === "buy" ? 1.0008 : 0.9992;
    const fillPrice = Number((price * slip).toFixed(order.venue === "polymarket" ? 4 : 2));
    const fee = fillPrice * order.qty * 0.0006;

    order.status = "filled";
    order.filledQty = order.qty;
    order.avgFillPrice = fillPrice;
    this.orders.unshift(order);

    const signed = order.side === "buy" ? order.qty : -order.qty;
    const key = order.marketId;
    const existing = this.positions.get(key);
    let realized = 0;

    if (!existing) {
      const m = this.sim.get(key);
      const { stop, target } = m ? this.computeStops(m, order.side, fillPrice) : { stop: 0, target: 0 };
      this.positions.set(key, {
        marketId: order.marketId,
        venue: order.venue,
        symbol: m?.symbol ?? order.marketId,
        qty: signed,
        avgPrice: fillPrice,
        strategyId: strat.id,
        stop,
        target,
        trailRef: fillPrice,
      });
    } else {
      const newQty = existing.qty + signed;
      if (Math.sign(newQty) === Math.sign(existing.qty) || existing.qty === 0) {
        const totalCost = existing.avgPrice * Math.abs(existing.qty) + fillPrice * Math.abs(signed);
        existing.avgPrice = Math.abs(newQty) > 0 ? totalCost / Math.abs(newQty) : fillPrice;
      } else {
        const closedQty = Math.min(Math.abs(signed), Math.abs(existing.qty));
        const dir = existing.qty > 0 ? 1 : -1;
        realized = (fillPrice - existing.avgPrice) * closedQty * dir;
        this.realizedPnl += realized;
      }
      if (Math.abs(newQty) < 1e-9) this.positions.delete(key);
      else existing.qty = newQty;
    }

    this.cash -= signed * fillPrice + fee;

    // strategy stats + streak/cooldown tracking
    if (realized !== 0) {
      strat.pnl += realized;
      strat.trades++;
      strat.winRate = (strat.winRate * (strat.trades - 1) + (realized >= 0 ? 1 : 0)) / strat.trades;

      if (realized >= 0) this.grossWin.set(strat.id, (this.grossWin.get(strat.id) ?? 0) + realized);
      else this.grossLoss.set(strat.id, (this.grossLoss.get(strat.id) ?? 0) - realized);
      const gw = this.grossWin.get(strat.id) ?? 0;
      const gl = this.grossLoss.get(strat.id) ?? 0;
      strat.profitFactor = gl > 0 ? gw / gl : gw > 0 ? 99 : 0;

      let streak = this.consecLosses.get(strat.id) ?? 0;
      streak = realized < 0 ? streak + 1 : 0;
      this.consecLosses.set(strat.id, streak);
      if (this.limits.maxConsecutiveLosses > 0 && streak >= this.limits.maxConsecutiveLosses) {
        this.cooldownUntil.set(strat.id, Date.now() + this.limits.cooldownSec * 1000);
        this.consecLosses.set(strat.id, 0);
        this.log("risk", `${strat.id}: ${this.limits.maxConsecutiveLosses} consecutive losses — cooling down ${this.limits.cooldownSec}s`, strat.id);
      }

      strat.equityCurve.push(strat.pnl);
      if (strat.equityCurve.length > 200) strat.equityCurve.shift();
      let peak = -Infinity;
      let dd = 0;
      for (const v of strat.equityCurve) {
        if (v > peak) peak = v;
        dd = Math.max(dd, peak - v);
      }
      strat.maxDrawdown = dd;
    } else {
      strat.equityCurve.push(strat.pnl);
      if (strat.equityCurve.length > 200) strat.equityCurve.shift();
    }

    this.log(
      "fill",
      `${order.mode.toUpperCase()} FILL ${order.side} ${order.qty.toFixed(4)} ${order.marketId} @ ${fillPrice}`,
      strat.id,
      order.marketId
    );
  }

  // ── position exits ──────────────────────────────────────────────────────────
  private checkPositionExits() {
    const trail = this.limits.trailingAtrMult;
    const toClose: Array<[string, string]> = [];
    for (const p of this.positions.values()) {
      const m = this.sim.get(p.marketId);
      if (!m || p.qty === 0 || (p.stop <= 0 && p.target <= 0)) continue;
      const price = m.price;
      const long = p.qty > 0;

      if (trail > 0 && p.stop > 0) {
        if (long && price > p.trailRef) {
          const d = p.trailRef - p.stop;
          p.trailRef = price;
          p.stop = price - d;
        } else if (!long && price < p.trailRef) {
          const d = p.stop - p.trailRef;
          p.trailRef = price;
          p.stop = price + d;
        }
      }

      if (p.stop > 0 && ((long && price <= p.stop) || (!long && price >= p.stop))) {
        toClose.push([p.marketId, "stop-loss"]);
      } else if (p.target > 0 && ((long && price >= p.target) || (!long && price <= p.target))) {
        toClose.push([p.marketId, "take-profit"]);
      }
    }
    for (const [id, reason] of toClose) this.closePosition(id, reason);
  }

  private closePosition(marketId: string, reason: string) {
    const p = this.positions.get(marketId);
    const m = this.sim.get(marketId);
    if (!p || !m || p.qty === 0) return;
    const strat = this.strategies.find((s) => s.id === p.strategyId) ?? this.manualStrat(m.venue);
    const order: Order = {
      id: nextId("ord"),
      ts: Date.now(),
      strategyId: strat.id,
      marketId,
      venue: p.venue,
      side: p.qty > 0 ? "sell" : "buy",
      type: "market",
      qty: Math.abs(p.qty),
      status: "pending",
      filledQty: 0,
      mode: strat.state === "live" ? "live" : "paper",
    };
    this.fill(order, m.price, strat);
    this.log("system", `Exit ${marketId}: ${reason}`, strat.id, marketId);
  }

  private manualStrat(venue: Venue): StrategyConfig {
    return {
      id: "manual", name: "Manual", kind: "manual", venueClass: venue, state: "paper",
      universe: [], params: [], budgetPct: 100, pnl: 0, trades: 0, winRate: 0,
      maxDrawdown: 0, profitFactor: 0, equityCurve: [0],
    };
  }

  // ── manual actions (from the UI) ────────────────────────────────────────────
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
    this.fill(order, m.price, this.manualStrat(m.venue));
    this.emit();
    return "ok";
  }

  flatten(marketId: string) {
    const p = this.positions.get(marketId);
    const m = this.sim.get(marketId);
    if (!p || !m) return;
    const order: Order = {
      id: nextId("ord"),
      ts: Date.now(),
      strategyId: "manual",
      marketId,
      venue: p.venue,
      side: p.qty > 0 ? "sell" : "buy",
      type: "market",
      qty: Math.abs(p.qty),
      status: "pending",
      filledQty: 0,
      mode: "paper",
    };
    this.fill(order, m.price, this.manualStrat(p.venue));
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

  // ── public read API ─────────────────────────────────────────────────────────
  snapshot(): PortfolioSnapshot {
    const balances: VenueBalance[] = (["polymarket", "crypto", "alpaca"] as Venue[]).map((venue) => ({
      venue,
      connected: false,
      cash: this.cash / 3,
      equity: this.equity() / 3,
      mode: "paper" as Mode,
    }));
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
