import { simulate, syntheticSeries, type BacktestResult, type BacktestOpts } from "./backtest";
import { evalComposed } from "./composedRules";
import type { Composed } from "../types";

// Backtest a user-composed rule-based strategy on synthetic history, reusing the
// shared simulate() loop and the same evalComposed() the live engine runs.
export function backtestComposed(c: Composed, opts: BacktestOpts = {}): BacktestResult {
  const bars = opts.bars ?? 1500;
  const series = syntheticSeries(bars, opts.startPrice ?? 100, opts.drift ?? 0.0002, opts.vol ?? 0.015, opts.seed ?? 12345);
  return simulate(series, (hist, price) => evalComposed(c, hist, price), opts);
}

// Convenience re-exports so existing imports keep working.
export { IND_LABELS, NEEDS_PERIOD, TEMPLATES, evalComposed, evalOperand } from "./composedRules";
export type { Composed, IndKind, Operand, Rule } from "../types";
