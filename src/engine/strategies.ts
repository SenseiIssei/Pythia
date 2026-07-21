import type { Market, StrategyConfig } from "../types";

// A strategy emits Intents — a desired *target* exposure in a market. It never
// talks to a venue; the engine turns intents into risk-checked orders.
export interface Intent {
  marketId: string;
  side: "buy" | "sell";
  // notional fraction of the strategy's budget to deploy on this signal (0..1)
  size: number;
  // 0..1 confidence, used for Kelly sizing
  confidence: number;
  reason: string;
}

function param(cfg: StrategyConfig, key: string, fallback: number): number {
  return cfg.params.find((p) => p.key === key)?.value ?? fallback;
}

// ── Prob-Edge (Polymarket) ────────────────────────────────────────────────
// Bet an outcome when the model probability beats the market's implied
// probability by more than a threshold (which must clear fees).
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
      size: Math.min(1, Math.abs(edge) / 0.2),
      confidence: Math.min(1, Math.abs(edge) / 0.15),
      reason: `model ${(m.modelProb * 100).toFixed(0)}% vs mkt ${(m.price * 100).toFixed(0)}% (edge ${(edge * 100).toFixed(1)}pp)`,
    });
  }
  return out;
}

// ── Momentum (crypto/equity) ──────────────────────────────────────────────
function momentum(cfg: StrategyConfig, markets: Map<string, Market>): Intent[] {
  const trigger = param(cfg, "trendPct", 0.015);
  const out: Intent[] = [];
  for (const id of cfg.universe) {
    const m = markets.get(id);
    if (!m || m.kind === "prediction") continue;
    if (m.change24h > trigger) {
      out.push({
        marketId: id,
        side: "buy",
        size: Math.min(1, m.change24h / (trigger * 4)),
        confidence: Math.min(1, m.change24h / (trigger * 3)),
        reason: `uptrend +${(m.change24h * 100).toFixed(1)}% > ${(trigger * 100).toFixed(1)}%`,
      });
    } else if (m.change24h < -trigger) {
      out.push({
        marketId: id,
        side: "sell",
        size: Math.min(1, -m.change24h / (trigger * 4)),
        confidence: Math.min(1, -m.change24h / (trigger * 3)),
        reason: `downtrend ${(m.change24h * 100).toFixed(1)}%`,
      });
    }
  }
  return out;
}

// ── Mean-Revert (crypto/equity) ───────────────────────────────────────────
function meanRevert(cfg: StrategyConfig, markets: Map<string, Market>): Intent[] {
  const band = param(cfg, "bandPct", 0.03);
  const out: Intent[] = [];
  for (const id of cfg.universe) {
    const m = markets.get(id);
    if (!m || m.kind === "prediction") continue;
    // fade a stretched move: if far above reference, sell; far below, buy
    if (m.change24h > band) {
      out.push({
        marketId: id,
        side: "sell",
        size: Math.min(1, m.change24h / (band * 3)),
        confidence: Math.min(1, m.change24h / (band * 2)),
        reason: `stretched +${(m.change24h * 100).toFixed(1)}% — fade`,
      });
    } else if (m.change24h < -band) {
      out.push({
        marketId: id,
        side: "buy",
        size: Math.min(1, -m.change24h / (band * 3)),
        confidence: Math.min(1, -m.change24h / (band * 2)),
        reason: `oversold ${(m.change24h * 100).toFixed(1)}% — buy`,
      });
    }
  }
  return out;
}

export function runStrategy(
  cfg: StrategyConfig,
  markets: Map<string, Market>
): Intent[] {
  if (cfg.state === "paused") return [];
  switch (cfg.kind) {
    case "prob-edge":
      return probEdge(cfg, markets);
    case "momentum":
      return momentum(cfg, markets);
    case "mean-revert":
      return meanRevert(cfg, markets);
    case "arb":
    case "manual":
    default:
      return []; // arb + manual are driven elsewhere (Phase 2 / user input)
  }
}

// ── Default strategy set ──────────────────────────────────────────────────
export function defaultStrategies(): StrategyConfig[] {
  return [
    {
      id: "prob-edge-1",
      name: "Prob-Edge · Polymarket",
      kind: "prob-edge",
      venueClass: "polymarket",
      state: "paper",
      universe: [
        "polymarket:fed-cut-2026",
        "polymarket:btc-100k-2026",
        "polymarket:election-turnout",
      ],
      params: [
        { key: "edgeThreshold", label: "Min edge (pp)", value: 0.05, min: 0.01, max: 0.3, step: 0.01 },
      ],
      budgetPct: 20,
      pnl: 0,
      trades: 0,
      winRate: 0,
      equityCurve: [0],
    },
    {
      id: "momentum-1",
      name: "Momentum · Crypto",
      kind: "momentum",
      venueClass: "crypto",
      state: "paper",
      universe: ["crypto:BTC/USD", "crypto:ETH/USD", "crypto:SOL/USD"],
      params: [
        { key: "trendPct", label: "Trend trigger", value: 0.015, min: 0.005, max: 0.1, step: 0.005 },
      ],
      budgetPct: 20,
      pnl: 0,
      trades: 0,
      winRate: 0,
      equityCurve: [0],
    },
    {
      id: "mean-revert-1",
      name: "Mean-Revert · Equities",
      kind: "mean-revert",
      venueClass: "alpaca",
      state: "paused",
      universe: ["alpaca:AAPL", "alpaca:NVDA"],
      params: [
        { key: "bandPct", label: "Deviation band", value: 0.03, min: 0.01, max: 0.15, step: 0.005 },
      ],
      budgetPct: 15,
      pnl: 0,
      trades: 0,
      winRate: 0,
      equityCurve: [0],
    },
  ];
}
