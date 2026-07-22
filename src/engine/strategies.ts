import type { Market, StrategyConfig, Side } from "../types";
import * as ind from "./indicators";
import { evalComposed } from "./composedRules";

// A strategy emits Intents — a desired *target* exposure in a market. Mirrors
// the Rust `engine::strategies` module so both runtimes behave identically.
export interface Intent {
  marketId: string;
  side: Side;
  size: number; // 0..1 fraction of the strategy budget to deploy
  confidence: number; // 0..1, used for Kelly sizing
  reason: string;
}

function param(cfg: StrategyConfig, key: string, fallback: number): number {
  return cfg.params.find((p) => p.key === key)?.value ?? fallback;
}
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));

// tradable (non-prediction) markets in the universe that have enough history
function* series(
  cfg: StrategyConfig,
  markets: Map<string, Market>,
  history: Map<string, number[]>
): Generator<[string, Market, number[]]> {
  for (const id of cfg.universe) {
    const m = markets.get(id);
    if (!m || m.kind === "prediction") continue;
    const h = history.get(id);
    if (!h) continue;
    yield [id, m, h];
  }
}

function emaCross(cfg: StrategyConfig, markets: Map<string, Market>, history: Map<string, number[]>): Intent[] {
  const fast = param(cfg, "fast", 9);
  const slow = param(cfg, "slow", 21);
  const out: Intent[] = [];
  for (const [id, , h] of series(cfg, markets, history)) {
    const f = ind.ema(h, fast);
    const s = ind.ema(h, slow);
    if (f === null || s === null || s === 0) continue;
    const spread = (f - s) / s;
    const strength = clamp01(Math.abs(spread) / 0.02);
    if (strength < 0.05) continue;
    out.push({
      marketId: id,
      side: f > s ? "buy" : "sell",
      size: strength,
      confidence: strength,
      reason: `EMA${fast}/${slow} spread ${(spread * 100).toFixed(2)}%`,
    });
  }
  return out;
}

function bollinger(cfg: StrategyConfig, markets: Map<string, Market>, history: Map<string, number[]>): Intent[] {
  const period = param(cfg, "period", 20);
  const k = param(cfg, "k", 2);
  const out: Intent[] = [];
  for (const [id, , h] of series(cfg, markets, history)) {
    const z = ind.zscore(h, period);
    if (z === null || Math.abs(z) <= k) continue;
    const strength = clamp01((Math.abs(z) - k) / k);
    out.push({
      marketId: id,
      side: z > 0 ? "sell" : "buy", // fade the stretch
      size: strength,
      confidence: strength,
      reason: `Bollinger z=${z.toFixed(2)} (>${k.toFixed(1)}σ)`,
    });
  }
  return out;
}

function rsiReversal(cfg: StrategyConfig, markets: Map<string, Market>, history: Map<string, number[]>): Intent[] {
  const period = param(cfg, "period", 14);
  const os = param(cfg, "oversold", 30);
  const ob = param(cfg, "overbought", 70);
  const out: Intent[] = [];
  for (const [id, , h] of series(cfg, markets, history)) {
    const r = ind.rsi(h, period);
    if (r === null) continue;
    if (r < os) {
      const s = clamp01((os - r) / os);
      out.push({ marketId: id, side: "buy", size: s, confidence: s, reason: `RSI ${r.toFixed(0)} < ${os.toFixed(0)} (oversold)` });
    } else if (r > ob) {
      const s = clamp01((r - ob) / (100 - ob));
      out.push({ marketId: id, side: "sell", size: s, confidence: s, reason: `RSI ${r.toFixed(0)} > ${ob.toFixed(0)} (overbought)` });
    }
  }
  return out;
}

function macdTrend(cfg: StrategyConfig, markets: Map<string, Market>, history: Map<string, number[]>): Intent[] {
  const out: Intent[] = [];
  for (const [id, m, h] of series(cfg, markets, history)) {
    const r = ind.macd(h);
    if (!r) continue;
    const hist = r.line - r.signal;
    const strength = clamp01(Math.abs(hist) / m.price / 0.001);
    if (strength < 0.1) continue;
    if (r.line > r.signal && r.line > 0) {
      out.push({ marketId: id, side: "buy", size: strength, confidence: strength, reason: `MACD ${r.line.toFixed(4)} > signal ${r.signal.toFixed(4)}` });
    } else if (r.line < r.signal && r.line < 0) {
      out.push({ marketId: id, side: "sell", size: strength, confidence: strength, reason: `MACD ${r.line.toFixed(4)} < signal ${r.signal.toFixed(4)}` });
    }
  }
  return out;
}

function breakout(cfg: StrategyConfig, markets: Map<string, Market>, history: Map<string, number[]>): Intent[] {
  const period = param(cfg, "period", 20);
  const out: Intent[] = [];
  for (const [id, m, h] of series(cfg, markets, history)) {
    if (h.length < period + 1) continue;
    const prior = h.slice(0, h.length - 1);
    const hi = ind.donchianHigh(prior, period);
    const lo = ind.donchianLow(prior, period);
    if (hi === null || lo === null) continue;
    if (m.price > hi) {
      out.push({ marketId: id, side: "buy", size: 0.8, confidence: 0.6, reason: `breakout > ${period}-bar high ${hi.toFixed(2)}` });
    } else if (m.price < lo) {
      out.push({ marketId: id, side: "sell", size: 0.8, confidence: 0.6, reason: `breakdown < ${period}-bar low ${lo.toFixed(2)}` });
    }
  }
  return out;
}

function probEdge(cfg: StrategyConfig, markets: Map<string, Market>): Intent[] {
  const threshold = param(cfg, "edgeThreshold", 0.05);
  const out: Intent[] = [];
  for (const id of cfg.universe) {
    const m = markets.get(id);
    if (!m || m.kind !== "prediction" || m.modelProb == null) continue;
    const edge = m.modelProb - m.price;
    if (Math.abs(edge) <= threshold) continue;
    out.push({
      marketId: id,
      side: edge > 0 ? "buy" : "sell",
      size: clamp01(Math.abs(edge) / 0.2),
      confidence: clamp01(Math.abs(edge) / 0.15),
      reason: `model ${(m.modelProb * 100).toFixed(0)}% vs mkt ${(m.price * 100).toFixed(0)}% (edge ${(edge * 100).toFixed(1)}pp)`,
    });
  }
  return out;
}

function multiTf(cfg: StrategyConfig, markets: Map<string, Market>, history: Map<string, number[]>): Intent[] {
  const fast = param(cfg, "fast", 9);
  const slow = param(cfg, "slow", 21);
  const htf = param(cfg, "htf", 50);
  const out: Intent[] = [];
  for (const [id, , h] of series(cfg, markets, history)) {
    const f = ind.ema(h, fast);
    const s = ind.ema(h, slow);
    const trend = ind.roc(h, htf);
    if (f === null || s === null || trend === null || s === 0) continue;
    const spread = (f - s) / s;
    const strength = Math.sqrt(clamp01(Math.abs(spread) / 0.02) * clamp01(Math.abs(trend) / 0.03));
    if (strength < 0.05) continue;
    if (f > s && trend > 0) {
      out.push({ marketId: id, side: "buy", size: strength, confidence: strength, reason: `MTF up: EMA${fast}>${slow} & HTF ${(trend * 100).toFixed(1)}%` });
    } else if (f < s && trend < 0) {
      out.push({ marketId: id, side: "sell", size: strength, confidence: strength, reason: `MTF down: EMA${fast}<${slow} & HTF ${(trend * 100).toFixed(1)}%` });
    }
  }
  return out;
}

function pairs(cfg: StrategyConfig, _markets: Map<string, Market>, history: Map<string, number[]>): Intent[] {
  if (cfg.universe.length < 2) return [];
  const period = param(cfg, "period", 30);
  const k = param(cfg, "k", 2);
  const a = cfg.universe[0];
  const b = cfg.universe[1];
  const ha = history.get(a);
  const hb = history.get(b);
  if (!ha || !hb) return [];
  const n = Math.min(ha.length, hb.length);
  if (n < period + 1) return [];
  const ratio: number[] = [];
  for (let i = 0; i < n; i++) {
    const eb = hb[hb.length - n + i];
    ratio.push(eb === 0 ? 1 : ha[ha.length - n + i] / eb);
  }
  const z = ind.zscore(ratio, period);
  if (z === null || Math.abs(z) <= k) return [];
  const strength = clamp01((Math.abs(z) - k) / k);
  const [sideA, sideB]: [Side, Side] = z > 0 ? ["sell", "buy"] : ["buy", "sell"];
  return [
    { marketId: a, side: sideA, size: strength, confidence: strength, reason: `pairs z=${z.toFixed(2)} — leg A` },
    { marketId: b, side: sideB, size: strength, confidence: strength, reason: `pairs z=${z.toFixed(2)} — leg B` },
  ];
}

export function runStrategy(
  cfg: StrategyConfig,
  markets: Map<string, Market>,
  history: Map<string, number[]>
): Intent[] {
  if (cfg.state === "paused") return [];
  switch (cfg.kind) {
    case "ema-cross":
      return emaCross(cfg, markets, history);
    case "bollinger":
      return bollinger(cfg, markets, history);
    case "rsi-reversal":
      return rsiReversal(cfg, markets, history);
    case "macd-trend":
      return macdTrend(cfg, markets, history);
    case "breakout":
      return breakout(cfg, markets, history);
    case "multi-tf":
      return multiTf(cfg, markets, history);
    case "pairs":
      return pairs(cfg, markets, history);
    case "prob-edge":
      return probEdge(cfg, markets);
    case "composed":
      return composed(cfg, markets, history);
    default:
      return [];
  }
}

// User-composed rule strategy: evaluate the rules on each market in the universe.
function composed(cfg: StrategyConfig, markets: Map<string, Market>, history: Map<string, number[]>): Intent[] {
  if (!cfg.rules) return [];
  const out: Intent[] = [];
  for (const [id, m, h] of series(cfg, markets, history)) {
    const sig = evalComposed(cfg.rules, h, m.price);
    if (sig) out.push({ marketId: id, side: sig.side, size: 0.8, confidence: 0.6, reason: `composed ${cfg.rules.direction} rules met` });
  }
  return out;
}

function mkParam(key: string, label: string, value: number, min: number, max: number, step: number) {
  return { key, label, value, min, max, step };
}

export function defaultStrategies(): StrategyConfig[] {
  const crypto = [
    "crypto:BTC/USD", "crypto:ETH/USD", "crypto:SOL/USD", "crypto:ADA/USD",
    "crypto:DOT/USD", "crypto:LINK/USD", "crypto:AVAX/USD", "crypto:XRP/USD", "crypto:LTC/USD",
  ];
  const equities = ["alpaca:AAPL", "alpaca:NVDA"];
  const base = { pnl: 0, trades: 0, winRate: 0, maxDrawdown: 0, profitFactor: 0, equityCurve: [0] };
  return [
    { id: "ema-cross-1", name: "EMA Cross · Crypto", kind: "ema-cross", venueClass: "crypto", state: "paper", universe: crypto,
      params: [mkParam("fast", "Fast EMA", 9, 3, 30, 1), mkParam("slow", "Slow EMA", 21, 10, 100, 1)], budgetPct: 18, ...base },
    { id: "multi-tf-1", name: "Multi-TF Momentum · Crypto", kind: "multi-tf", venueClass: "crypto", state: "paper", universe: crypto,
      params: [mkParam("fast", "Fast EMA", 9, 3, 30, 1), mkParam("slow", "Slow EMA", 21, 10, 100, 1), mkParam("htf", "HTF ROC", 50, 20, 150, 5)], budgetPct: 15, ...base },
    { id: "macd-1", name: "MACD Trend · Crypto", kind: "macd-trend", venueClass: "crypto", state: "paper", universe: crypto,
      params: [], budgetPct: 15, ...base },
    { id: "bollinger-1", name: "Bollinger Revert · Crypto", kind: "bollinger", venueClass: "crypto", state: "paused", universe: crypto,
      params: [mkParam("period", "Period", 20, 5, 60, 1), mkParam("k", "Band σ", 2, 1, 3.5, 0.1)], budgetPct: 15, ...base },
    { id: "rsi-1", name: "RSI Reversal · Crypto", kind: "rsi-reversal", venueClass: "crypto", state: "paused", universe: crypto,
      params: [mkParam("period", "Period", 14, 5, 30, 1), mkParam("oversold", "Oversold", 30, 10, 45, 1), mkParam("overbought", "Overbought", 70, 55, 90, 1)], budgetPct: 15, ...base },
    { id: "breakout-1", name: "Donchian Breakout · Equities", kind: "breakout", venueClass: "alpaca", state: "paused", universe: equities,
      params: [mkParam("period", "Channel", 20, 5, 60, 1)], budgetPct: 12, ...base },
    { id: "pairs-1", name: "Pairs · BTC/ETH", kind: "pairs", venueClass: "crypto", state: "paused", universe: ["crypto:BTC/USD", "crypto:ETH/USD"],
      params: [mkParam("period", "Z period", 30, 10, 90, 5), mkParam("k", "Z entry σ", 2, 1, 3.5, 0.1)], budgetPct: 12, ...base },
    { id: "prob-edge-1", name: "Prob-Edge · Polymarket", kind: "prob-edge", venueClass: "polymarket", state: "paper",
      universe: ["polymarket:fed-cut-2026", "polymarket:btc-100k-2026"],
      params: [mkParam("edgeThreshold", "Min edge (pp)", 0.05, 0.01, 0.3, 0.01)], budgetPct: 15, ...base },
  ];
}
