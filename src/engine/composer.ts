import * as ind from "./indicators";
import { simulate, syntheticSeries, type BacktestResult, type BacktestOpts, type Signal } from "./backtest";

// A user-composed, rule-based strategy — built in the UI and backtested here.
// Research/backtest-only for now: it isn't wired into the live engine (that
// would need the rules serialized into both the Rust and TS runtimes).

export type IndKind = "price" | "rsi" | "ema" | "sma" | "zscore" | "roc" | "macdHist" | "atr";

export const IND_LABELS: Record<IndKind, string> = {
  price: "Price",
  rsi: "RSI",
  ema: "EMA",
  sma: "SMA",
  zscore: "Z-score",
  roc: "ROC %",
  macdHist: "MACD hist",
  atr: "ATR",
};

/** Which indicators take a period parameter. */
export const NEEDS_PERIOD: Record<IndKind, boolean> = {
  price: false,
  rsi: true,
  ema: true,
  sma: true,
  zscore: true,
  roc: true,
  macdHist: false,
  atr: true,
};

export interface Operand {
  kind: IndKind;
  period: number;
}

export interface Rule {
  left: Operand;
  op: "<" | ">";
  rightMode: "const" | "indicator";
  rightConst: number;
  rightOperand: Operand;
}

export interface Composed {
  direction: "long" | "short";
  rules: Rule[];
}

export function evalOperand(o: Operand, hist: number[], price: number): number | null {
  switch (o.kind) {
    case "price":
      return price;
    case "rsi":
      return ind.rsi(hist, o.period);
    case "ema":
      return ind.ema(hist, o.period);
    case "sma":
      return ind.sma(hist, o.period);
    case "zscore":
      return ind.zscore(hist, o.period);
    case "roc": {
      const r = ind.roc(hist, o.period);
      return r === null ? null : r * 100; // percent for readable thresholds
    }
    case "atr":
      return ind.atrProxy(hist, o.period);
    case "macdHist": {
      const m = ind.macd(hist);
      return m ? m.line - m.signal : null;
    }
  }
}

/** All entry rules must pass (AND). Returns a signal in the chosen direction. */
export function evalComposed(c: Composed, hist: number[], price: number): Signal | null {
  if (c.rules.length === 0) return null;
  for (const r of c.rules) {
    const l = evalOperand(r.left, hist, price);
    if (l === null) return null;
    const rv = r.rightMode === "indicator" ? evalOperand(r.rightOperand, hist, price) : r.rightConst;
    if (rv === null) return null;
    const pass = r.op === "<" ? l < rv : l > rv;
    if (!pass) return null;
  }
  return { side: c.direction === "long" ? "buy" : "sell", size: 1 };
}

export function backtestComposed(c: Composed, opts: BacktestOpts = {}): BacktestResult {
  const bars = opts.bars ?? 1500;
  const series = syntheticSeries(bars, opts.startPrice ?? 100, opts.drift ?? 0.0002, opts.vol ?? 0.015, opts.seed ?? 12345);
  return simulate(series, (hist, price) => evalComposed(c, hist, price), opts);
}

// ── ready-made templates ────────────────────────────────────────────────────
const op = (kind: IndKind, period = 14): Operand => ({ kind, period });
const rule = (left: Operand, o: "<" | ">", constVal: number): Rule => ({ left, op: o, rightMode: "const", rightConst: constVal, rightOperand: op("ema", 50) });
const ruleInd = (left: Operand, o: "<" | ">", right: Operand): Rule => ({ left, op: o, rightMode: "indicator", rightConst: 0, rightOperand: right });

export const TEMPLATES: { name: string; composed: Composed }[] = [
  { name: "RSI oversold (long)", composed: { direction: "long", rules: [rule(op("rsi", 14), "<", 30)] } },
  { name: "Trend follow (long)", composed: { direction: "long", rules: [ruleInd(op("price"), ">", op("ema", 50)), rule(op("roc", 20), ">", 1)] } },
  { name: "Bollinger fade (short)", composed: { direction: "short", rules: [rule(op("zscore", 20), ">", 2)] } },
  { name: "MACD momentum (long)", composed: { direction: "long", rules: [rule(op("macdHist"), ">", 0), ruleInd(op("price"), ">", op("sma", 30))] } },
];
