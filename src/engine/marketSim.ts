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
  "crypto:BTC/USD": { drift: 0.00002, vol: 0.0018, base: 66000 },
  "crypto:ETH/USD": { drift: 0.00001, vol: 0.0022, base: 3560 },
  "crypto:SOL/USD": { drift: 0.00004, vol: 0.0035, base: 161 },
  "alpaca:AAPL": { drift: 0.000005, vol: 0.0009, base: 225.7 },
  "alpaca:NVDA": { drift: 0.00003, vol: 0.0016, base: 136 },
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
