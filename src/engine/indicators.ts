// Technical indicators over a close-price series (oldest first, latest last).
// A 1:1 mirror of the Rust `engine::indicators` module so the browser and
// native builds produce identical signals. Return null when data is insufficient.

export function sma(s: number[], n: number): number | null {
  if (n === 0 || s.length < n) return null;
  let sum = 0;
  for (let i = s.length - n; i < s.length; i++) sum += s[i];
  return sum / n;
}

export function ema(s: number[], n: number): number | null {
  if (n === 0 || s.length < n) return null;
  const k = 2 / (n + 1);
  let e = 0;
  for (let i = 0; i < n; i++) e += s[i];
  e /= n;
  for (let i = n; i < s.length; i++) e = s[i] * k + e * (1 - k);
  return e;
}

export function stddev(s: number[], n: number): number | null {
  if (n < 2 || s.length < n) return null;
  const w = s.slice(s.length - n);
  const m = w.reduce((a, b) => a + b, 0) / n;
  const varr = w.reduce((a, b) => a + (b - m) * (b - m), 0) / n;
  return Math.sqrt(varr);
}

export function zscore(s: number[], n: number): number | null {
  const m = sma(s, n);
  const sd = stddev(s, n);
  if (m === null || sd === null) return null;
  if (sd === 0) return 0;
  return (s[s.length - 1] - m) / sd;
}

export function roc(s: number[], n: number): number | null {
  if (n === 0 || s.length <= n) return null;
  const past = s[s.length - 1 - n];
  if (past === 0) return null;
  return s[s.length - 1] / past - 1;
}

export function rsi(s: number[], n: number): number | null {
  if (n === 0 || s.length < n + 1) return null;
  const w = s.slice(s.length - n - 1);
  let gain = 0;
  let loss = 0;
  for (let i = 1; i < w.length; i++) {
    const d = w[i] - w[i - 1];
    if (d >= 0) gain += d;
    else loss -= d;
  }
  const avgLoss = loss / n;
  if (avgLoss === 0) return 100;
  const rs = gain / n / avgLoss;
  return 100 - 100 / (1 + rs);
}

export function donchianHigh(s: number[], n: number): number | null {
  if (n === 0 || s.length < n) return null;
  let hi = -Infinity;
  for (let i = s.length - n; i < s.length; i++) hi = Math.max(hi, s[i]);
  return hi;
}

export function donchianLow(s: number[], n: number): number | null {
  if (n === 0 || s.length < n) return null;
  let lo = Infinity;
  for (let i = s.length - n; i < s.length; i++) lo = Math.min(lo, s[i]);
  return lo;
}

export function atrProxy(s: number[], n: number): number | null {
  if (n === 0 || s.length < n + 1) return null;
  const w = s.slice(s.length - n - 1);
  let sum = 0;
  for (let i = 1; i < w.length; i++) sum += Math.abs(w[i] - w[i - 1]);
  return sum / n;
}

export function retVol(s: number[], n: number): number | null {
  if (n < 2 || s.length < n + 1) return null;
  const w = s.slice(s.length - n - 1);
  const rets: number[] = [];
  for (let i = 1; i < w.length; i++) rets.push(w[i - 1] !== 0 ? w[i] / w[i - 1] - 1 : 0);
  const m = rets.reduce((a, b) => a + b, 0) / rets.length;
  const varr = rets.reduce((a, b) => a + (b - m) * (b - m), 0) / rets.length;
  return Math.sqrt(varr);
}

export function macd(s: number[]): { line: number; signal: number } | null {
  const FAST = 12;
  const SLOW = 26;
  const SIG = 9;
  if (s.length < SLOW + SIG) return null;
  const lineSeries: number[] = [];
  for (let i = s.length - SIG; i < s.length; i++) {
    const slice = s.slice(0, i + 1);
    const f = ema(slice, FAST);
    const sl = ema(slice, SLOW);
    if (f === null || sl === null) return null;
    lineSeries.push(f - sl);
  }
  const line = lineSeries[lineSeries.length - 1];
  const signal = ema(lineSeries, SIG);
  if (signal === null) return null;
  return { line, signal };
}
