import type { Market } from "../types";

// A small deterministic-ish market simulator so the whole cockpit is alive in
// paper mode with zero external connections. In Phase 1 this is replaced by real
// read-only market data from the venue connectors (Polymarket/Kraken/Alpaca).

interface SimState {
  drift: number; // per-tick drift
  vol: number; // per-tick volatility
  base: number; // reference price for change24h
}

const seedMarkets: Market[] = [
  {
    id: "crypto:BTC/USD",
    venue: "crypto",
    symbol: "BTC/USD",
    kind: "crypto",
    price: 67250,
    change24h: 0.018,
    liquidity: 4_200_000,
    updatedAt: Date.now(),
  },
  {
    id: "crypto:ETH/USD",
    venue: "crypto",
    symbol: "ETH/USD",
    kind: "crypto",
    price: 3520,
    change24h: -0.012,
    liquidity: 2_100_000,
    updatedAt: Date.now(),
  },
  {
    id: "crypto:SOL/USD",
    venue: "crypto",
    symbol: "SOL/USD",
    kind: "crypto",
    price: 168.4,
    change24h: 0.043,
    liquidity: 900_000,
    updatedAt: Date.now(),
  },
  { id: "crypto:ADA/USD", venue: "crypto", symbol: "ADA/USD", kind: "crypto", price: 0.45, change24h: 0.01, liquidity: 300_000, updatedAt: Date.now() },
  { id: "crypto:DOT/USD", venue: "crypto", symbol: "DOT/USD", kind: "crypto", price: 6.2, change24h: -0.008, liquidity: 250_000, updatedAt: Date.now() },
  { id: "crypto:LINK/USD", venue: "crypto", symbol: "LINK/USD", kind: "crypto", price: 14.3, change24h: 0.02, liquidity: 400_000, updatedAt: Date.now() },
  { id: "crypto:AVAX/USD", venue: "crypto", symbol: "AVAX/USD", kind: "crypto", price: 27.5, change24h: 0.03, liquidity: 350_000, updatedAt: Date.now() },
  { id: "crypto:XRP/USD", venue: "crypto", symbol: "XRP/USD", kind: "crypto", price: 0.52, change24h: 0.005, liquidity: 600_000, updatedAt: Date.now() },
  { id: "crypto:LTC/USD", venue: "crypto", symbol: "LTC/USD", kind: "crypto", price: 72.0, change24h: -0.005, liquidity: 200_000, updatedAt: Date.now() },
  {
    id: "alpaca:AAPL",
    venue: "alpaca",
    symbol: "AAPL",
    kind: "equity",
    price: 227.1,
    change24h: 0.006,
    liquidity: 1_500_000,
    updatedAt: Date.now(),
  },
  {
    id: "alpaca:NVDA",
    venue: "alpaca",
    symbol: "NVDA",
    kind: "equity",
    price: 138.9,
    change24h: 0.021,
    liquidity: 3_300_000,
    updatedAt: Date.now(),
  },
  { id: "alpaca:MSFT", venue: "alpaca", symbol: "MSFT", kind: "equity", price: 428.0, change24h: 0.004, liquidity: 1_200_000, updatedAt: Date.now() },
  { id: "alpaca:AMZN", venue: "alpaca", symbol: "AMZN", kind: "equity", price: 186.4, change24h: 0.009, liquidity: 1_800_000, updatedAt: Date.now() },
  { id: "alpaca:TSLA", venue: "alpaca", symbol: "TSLA", kind: "equity", price: 248.5, change24h: -0.012, liquidity: 2_600_000, updatedAt: Date.now() },
  {
    id: "polymarket:fed-cut-2026",
    venue: "polymarket",
    symbol: "Fed cuts rates before Sep 2026?",
    kind: "prediction",
    price: 0.62,
    change24h: 0.03,
    modelProb: 0.71,
    liquidity: 320_000,
    updatedAt: Date.now(),
  },
  {
    id: "polymarket:btc-100k-2026",
    venue: "polymarket",
    symbol: "BTC above $100k in 2026?",
    kind: "prediction",
    price: 0.44,
    change24h: -0.02,
    modelProb: 0.52,
    liquidity: 510_000,
    updatedAt: Date.now(),
  },
  {
    id: "polymarket:election-turnout",
    venue: "polymarket",
    symbol: "Record turnout in next election?",
    kind: "prediction",
    price: 0.38,
    change24h: 0.01,
    modelProb: 0.35,
    liquidity: 180_000,
    updatedAt: Date.now(),
  },
];

const simParams: Record<string, SimState> = {
  "crypto:BTC/USD": { drift: 0.0004, vol: 0.0022, base: 66000 },
  "crypto:ETH/USD": { drift: 0.00038, vol: 0.0024, base: 3560 },
  "crypto:SOL/USD": { drift: 0.00045, vol: 0.003, base: 161 },
  "crypto:ADA/USD": { drift: 0.00035, vol: 0.003, base: 0.44 },
  "crypto:DOT/USD": { drift: 0.00035, vol: 0.0029, base: 6.25 },
  "crypto:LINK/USD": { drift: 0.0004, vol: 0.0032, base: 14.0 },
  "crypto:AVAX/USD": { drift: 0.00042, vol: 0.0033, base: 26.7 },
  "crypto:XRP/USD": { drift: 0.00035, vol: 0.0028, base: 0.517 },
  "crypto:LTC/USD": { drift: 0.00032, vol: 0.0026, base: 72.4 },
  "alpaca:AAPL": { drift: 0.000005, vol: 0.0009, base: 225.7 },
  "alpaca:NVDA": { drift: 0.00003, vol: 0.0016, base: 136 },
  "alpaca:MSFT": { drift: 0.000006, vol: 0.0008, base: 426 },
  "alpaca:AMZN": { drift: 0.00001, vol: 0.0011, base: 185 },
  "alpaca:TSLA": { drift: 0.000004, vol: 0.0022, base: 250 },
  "polymarket:fed-cut-2026": { drift: 0, vol: 0.004, base: 0.6 },
  "polymarket:btc-100k-2026": { drift: 0, vol: 0.005, base: 0.45 },
  "polymarket:election-turnout": { drift: 0, vol: 0.003, base: 0.37 },
};

function gaussian(): number {
  // Box–Muller
  let u = 0;
  let v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

export class MarketSim {
  private markets: Map<string, Market>;

  constructor() {
    this.markets = new Map(seedMarkets.map((m) => [m.id, { ...m }]));
  }

  list(): Market[] {
    return [...this.markets.values()];
  }

  get(id: string): Market | undefined {
    return this.markets.get(id);
  }

  /** Advance every market one tick with a bounded random walk. */
  tick(): Market[] {
    const now = Date.now();
    for (const m of this.markets.values()) {
      const p = simParams[m.id];
      if (!p) continue;
      const shock = p.drift + p.vol * gaussian();
      let next = m.price * (1 + shock);
      if (m.kind === "prediction") {
        // probabilities are clamped to a sane (0.02 .. 0.98) band
        next = Math.min(0.98, Math.max(0.02, m.price + shock));
      }
      m.price = Number(next.toFixed(m.kind === "prediction" ? 3 : 2));
      m.change24h = Number(((m.price - p.base) / p.base).toFixed(4));
      m.updatedAt = now;
    }
    return this.list();
  }
}
