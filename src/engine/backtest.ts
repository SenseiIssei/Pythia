import type { StrategyConfig, Market } from "../types";
import { runStrategy } from "./strategies";
import * as ind from "./indicators";

// A self-contained, deterministic walk-forward backtester. It reuses the exact
// live strategy signal logic (`runStrategy`) over a synthetic price series, so a
// good/bad backtest reflects the same code that trades in the engine.
//
// Single-asset technical strategies are supported; pairs / prob-edge / manual
// need multi-asset or model inputs and are reported as unsupported here.

export interface BacktestResult {
  ok: boolean;
  message?: string;
  bars: number;
  trades: number;
  totalReturnPct: number;
  sharpe: number;
  maxDrawdownPct: number;
  winRate: number;
  profitFactor: number;
  equityCurve: number[];
}

export interface BacktestOpts {
  bars?: number;
  seed?: number;
  startPrice?: number;
  drift?: number;
  vol?: number;
  stopAtr?: number;
  tpAtr?: number;
  feeBps?: number;
}

// mulberry32 — a small deterministic PRNG (seed → reproducible series)
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function gauss(r: () => number): number {
  let u = 0;
  let v = 0;
  while (u === 0) u = r();
  while (v === 0) v = r();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

export function syntheticSeries(bars: number, start: number, drift: number, vol: number, seed: number): number[] {
  const r = rng(seed);
  const s = [start];
  let p = start;
  for (let i = 1; i < bars; i++) {
    p *= 1 + drift + vol * gauss(r);
    if (p < 0.01) p = 0.01;
    s.push(p);
  }
  return s;
}

export interface Signal {
  side: "buy" | "sell";
  size: number; // 0..1 fraction of the 20%-of-equity slug
}

/**
 * Core walk-forward simulation shared by the strategy backtester and the
 * composer. `signalAt` returns a new-position signal (only consulted when flat);
 * exits are handled by ATR stop-loss / take-profit.
 */
export function simulate(series: number[], signalAt: (hist: number[], price: number) => Signal | null, opts: BacktestOpts = {}): BacktestResult {
  const bars = series.length;
  const fee = (opts.feeBps ?? 6) / 10000;
  const stopAtr = opts.stopAtr ?? 3;
  const tpAtr = opts.tpAtr ?? 5;

  const START = 10_000;
  let cash = START;
  let equity = START;
  let pos = 0;
  let entry = 0;
  let stop = 0;
  let target = 0;
  const equityCurve: number[] = [];
  let peak = START;
  let maxDD = 0;
  let wins = 0;
  let grossWin = 0;
  let grossLoss = 0;
  let trades = 0;

  const closePos = (price: number) => {
    const pnl = (price - entry) * pos;
    cash += pnl - Math.abs(pos * price) * fee;
    if (pnl >= 0) {
      wins++;
      grossWin += pnl;
    } else {
      grossLoss += -pnl;
    }
    trades++;
    pos = 0;
  };

  const warm = 60;
  for (let i = warm; i < bars; i++) {
    const hist = series.slice(0, i + 1);
    const price = series[i];

    if (pos !== 0) {
      const long = pos > 0;
      const hitStop = stop > 0 && (long ? price <= stop : price >= stop);
      const hitTarget = target > 0 && (long ? price >= target : price <= target);
      if (hitStop || hitTarget) closePos(price);
    }

    if (pos === 0) {
      const sig = signalAt(hist, price);
      if (sig) {
        const atr = ind.atrProxy(hist, 14) ?? 0;
        const notional = equity * 0.2 * sig.size;
        pos = (sig.side === "buy" ? 1 : -1) * (notional / price);
        entry = price;
        cash -= Math.abs(pos * price) * fee;
        if (atr > 0) {
          stop = sig.side === "buy" ? price - stopAtr * atr : price + stopAtr * atr;
          target = sig.side === "buy" ? price + tpAtr * atr : price - tpAtr * atr;
        } else {
          stop = 0;
          target = 0;
        }
      }
    }

    equity = cash + pos * price;
    equityCurve.push(equity);
    if (equity > peak) peak = equity;
    maxDD = Math.max(maxDD, ((peak - equity) / peak) * 100);
  }
  if (pos !== 0) closePos(series[bars - 1]);

  const totalReturnPct = (cash / START - 1) * 100;
  const rets: number[] = [];
  for (let i = 1; i < equityCurve.length; i++) {
    const p = equityCurve[i - 1];
    if (p > 0) rets.push(equityCurve[i] / p - 1);
  }
  const mean = rets.reduce((a, b) => a + b, 0) / (rets.length || 1);
  const sd = Math.sqrt(rets.reduce((a, b) => a + (b - mean) * (b - mean), 0) / (rets.length || 1));
  const sharpe = sd > 0 ? (mean / sd) * Math.sqrt(252) : 0;
  const profitFactor = grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? 99 : 0;
  const winRate = trades > 0 ? wins / trades : 0;

  return { ok: true, bars, trades, totalReturnPct, sharpe, maxDrawdownPct: maxDD, winRate, profitFactor, equityCurve };
}

export function backtest(cfg: StrategyConfig, opts: BacktestOpts = {}): BacktestResult {
  const empty = { bars: 0, trades: 0, totalReturnPct: 0, sharpe: 0, maxDrawdownPct: 0, winRate: 0, profitFactor: 0, equityCurve: [] };
  if (cfg.kind === "pairs" || cfg.kind === "prob-edge" || cfg.kind === "manual" || cfg.kind === "arb") {
    return { ok: false, message: `${cfg.kind} needs multi-asset/model inputs — not in the single-asset backtester`, ...empty };
  }
  const bars = opts.bars ?? 1500;
  const marketId = cfg.universe[0] ?? "crypto:BTC/USD";
  const series = syntheticSeries(bars, opts.startPrice ?? 100, opts.drift ?? 0.0002, opts.vol ?? 0.015, opts.seed ?? 12345);
  return simulate(
    series,
    (hist, price) => {
      const m: Market = { id: marketId, venue: cfg.venueClass, symbol: marketId, kind: "crypto", price, change24h: 0, updatedAt: 0 };
      const intents = runStrategy(cfg, new Map([[marketId, m]]), new Map([[marketId, hist]]));
      const intent = intents.find((x) => x.marketId === marketId);
      return intent ? { side: intent.side, size: intent.size } : null;
    },
    opts
  );
}
