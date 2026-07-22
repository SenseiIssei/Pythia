import type { StrategyConfig } from "../types";
import { backtest, type BacktestOpts } from "./backtest";

// Walk-forward parameter optimization + Monte-Carlo robustness. Everything
// reuses the deterministic backtester, so a strategy that looks good here is
// good across many random histories — not just one lucky seed.

export interface MonteCarlo {
  seeds: number;
  medianReturn: number;
  meanReturn: number;
  bestReturn: number;
  worstReturn: number;
  pctProfitable: number;
  worstDD: number;
  medianSharpe: number;
  returns: number[];
}

export interface SweepPoint {
  params: Record<string, number>;
  medianReturn: number;
  medianSharpe: number;
  medianPF: number;
  worstDD: number;
  pctProfitable: number;
  score: number; // robustness score used for ranking
}

function median(xs: number[]): number {
  if (xs.length === 0) return 0;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/** A fixed, deterministic set of seeds so runs are reproducible. `base` lets
 *  callers pick a disjoint range (e.g. out-of-sample) that never overlaps. */
function seedList(n: number, base = 1000): number[] {
  const out: number[] = [];
  for (let i = 0; i < n; i++) out.push(base + i * 97);
  return out;
}

function withParams(cfg: StrategyConfig, params: Record<string, number>): StrategyConfig {
  return {
    ...cfg,
    params: cfg.params.map((p) => (p.key in params ? { ...p, value: params[p.key] } : p)),
  };
}

/** Run the backtest across `seeds` random histories and aggregate the spread. */
export function monteCarlo(cfg: StrategyConfig, seeds: number, opts: BacktestOpts = {}, seedBase = 1000): MonteCarlo {
  const returns: number[] = [];
  const sharpes: number[] = [];
  const dds: number[] = [];
  for (const seed of seedList(seeds, seedBase)) {
    const r = backtest(cfg, { ...opts, seed });
    if (!r.ok) continue;
    returns.push(r.totalReturnPct);
    sharpes.push(r.sharpe);
    dds.push(r.maxDrawdownPct);
  }
  const profitable = returns.filter((x) => x > 0).length;
  return {
    seeds: returns.length,
    medianReturn: median(returns),
    meanReturn: returns.reduce((a, b) => a + b, 0) / (returns.length || 1),
    bestReturn: returns.length ? Math.max(...returns) : 0,
    worstReturn: returns.length ? Math.min(...returns) : 0,
    pctProfitable: returns.length ? profitable / returns.length : 0,
    worstDD: dds.length ? Math.max(...dds) : 0,
    medianSharpe: median(sharpes),
    returns,
  };
}

/**
 * Auto-build a small parameter grid from a strategy's params: up to 3 values
 * per param (below / at / above the current value), at most the first 3 params,
 * so the total combination count stays responsive.
 */
export function autoGrid(cfg: StrategyConfig): Record<string, number[]> {
  const grid: Record<string, number[]> = {};
  for (const p of cfg.params.slice(0, 3)) {
    const round = (v: number) => {
      const stepped = Math.round(v / p.step) * p.step;
      return Number(Math.max(p.min, Math.min(p.max, stepped)).toFixed(4));
    };
    const values = [...new Set([round(p.value * 0.6), round(p.value), round(p.value * 1.5)])];
    grid[p.key] = values;
  }
  return grid;
}

function combos(grid: Record<string, number[]>): Record<string, number>[] {
  const keys = Object.keys(grid);
  let out: Record<string, number>[] = [{}];
  for (const k of keys) {
    const next: Record<string, number>[] = [];
    for (const base of out) for (const v of grid[k]) next.push({ ...base, [k]: v });
    out = next;
  }
  return out;
}

/** Sweep the grid; each combo is scored by its robustness across seeds. */
export function sweep(cfg: StrategyConfig, grid: Record<string, number[]>, seeds: number, opts: BacktestOpts = {}, seedBase = 1000): SweepPoint[] {
  const points: SweepPoint[] = [];
  for (const params of combos(grid)) {
    const mc = monteCarlo(withParams(cfg, params), seeds, opts, seedBase);
    // robustness score: reward median return & consistency, punish deep drawdowns
    const score = mc.medianReturn * mc.pctProfitable - mc.worstDD * 0.25;
    points.push({
      params,
      medianReturn: mc.medianReturn,
      medianSharpe: mc.medianSharpe,
      medianPF: 0, // PF omitted from MC aggregate to keep it light
      worstDD: mc.worstDD,
      pctProfitable: mc.pctProfitable,
      score,
    });
  }
  points.sort((a, b) => b.score - a.score);
  return points;
}

export interface WalkForward {
  best: Record<string, number>;
  inSample: MonteCarlo;
  outOfSample: MonteCarlo;
  degradationPct: number; // IS median return − OOS median return (higher = more overfit)
  holdsUp: boolean; // OOS still profitable and not far below IS
}

/**
 * Optimize on one set of random histories (in-sample), then evaluate the winning
 * params on a *disjoint* set (out-of-sample). A big drop OOS = overfitting.
 */
export function walkForward(cfg: StrategyConfig, grid: Record<string, number[]>, seeds: number, opts: BacktestOpts = {}): WalkForward {
  const isPoints = sweep(cfg, grid, seeds, opts, 1000); // in-sample seed range
  const best = isPoints[0]?.params ?? {};
  const bestCfg = withParams(cfg, best);
  const inSample = monteCarlo(bestCfg, seeds, opts, 1000);
  const outOfSample = monteCarlo(bestCfg, seeds, opts, 900_000); // disjoint OOS seed range
  const degradationPct = inSample.medianReturn - outOfSample.medianReturn;
  const holdsUp = outOfSample.medianReturn > 0 && outOfSample.pctProfitable >= 0.5 && degradationPct < Math.max(2, Math.abs(inSample.medianReturn) * 0.6);
  return { best, inSample, outOfSample, degradationPct, holdsUp };
}
