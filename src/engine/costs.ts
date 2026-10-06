// The cost model, read from the same `config/costs.json` the Rust core embeds
// and the Python research lab reads. One file, three readers, so the browser
// paper engine, the backtester and the native engine charge the same costs.
//
// The numbers are defaults from public fee schedules and typical spreads, to be
// calibrated from recorded data. See `crates/pythia-core/src/costs.rs` for the
// model itself; this is the same arithmetic, kept small on purpose.

import table from "../../config/costs.json";
import type { CostModel, CostVenue, PnlBreakdown, Venue } from "../types";

interface VenueEntry extends CostModel {
  label: string;
  symbols: Record<string, Partial<CostModel>>;
}

const VENUES = (table as unknown as { venues: Record<string, VenueEntry> }).venues;

/** Used only for a venue the file does not list: expensive, never free. */
const UNKNOWN_VENUE: CostModel = {
  takerBps: 50,
  makerBps: 30,
  halfSpreadBps: 25,
  impactCoeff: 25,
  borrowBpsYr: 100,
  minNotional: 10,
  defaultDepth: 10_000,
};

/** Above this share of gross, costs are the story (PROFIT-PLAN §1). */
export const COST_HEAVY_SHARE = 0.4;

/** The cost venue for an engine venue. Crypto is charged as Kraken unless told otherwise. */
export function costVenueFor(venue: Venue, crypto: CostVenue = "kraken"): CostVenue {
  if (venue === "alpaca") return "alpaca";
  if (venue === "polymarket") return "polymarket";
  return crypto;
}

/** The model for one instrument on one venue: venue defaults, then any per-symbol override. */
export function modelFor(venue: CostVenue, symbol: string): CostModel {
  const v = VENUES[venue];
  if (!v) return UNKNOWN_VENUE;
  const sym = symbol.trim().toUpperCase();
  const base = sym.split(/[/-]/)[0] ?? sym;
  const o = v.symbols?.[sym] ?? v.symbols?.[base] ?? {};
  return {
    takerBps: o.takerBps ?? v.takerBps,
    makerBps: o.makerBps ?? v.makerBps,
    halfSpreadBps: o.halfSpreadBps ?? v.halfSpreadBps,
    impactCoeff: o.impactCoeff ?? v.impactCoeff,
    borrowBpsYr: o.borrowBpsYr ?? v.borrowBpsYr,
    minNotional: o.minNotional ?? v.minNotional,
    defaultDepth: o.defaultDepth ?? v.defaultDepth ?? 0,
  };
}

/** Impact in bps: `impactCoeff * sqrt(notional / depth)`, the square-root law. */
export function impactBps(m: CostModel, notional: number, depth?: number): number {
  const d = depth && depth > 0 ? depth : m.defaultDepth;
  if (!(d > 0) || !(notional > 0) || !(m.impactCoeff > 0)) return 0;
  return m.impactCoeff * Math.sqrt(notional / d);
}

/** Half-spread plus impact for one aggressive side, in bps. */
export function slippageBps(m: CostModel, notional: number, depth?: number): number {
  return m.halfSpreadBps + impactBps(m, notional, depth);
}

/** Expected cost of a round trip (two taker sides), in bps of notional. */
export function roundTripBps(m: CostModel, notional: number, depth?: number): number {
  return 2 * (m.takerBps + slippageBps(m, notional, depth));
}

/** Every cost component times `k` (the cost-sensitivity stress). */
export function scaled(m: CostModel, k: number): CostModel {
  const f = Math.max(0, k);
  return {
    ...m,
    takerBps: m.takerBps * f,
    makerBps: m.makerBps * f,
    halfSpreadBps: m.halfSpreadBps * f,
    impactCoeff: m.impactCoeff * f,
    borrowBpsYr: m.borrowBpsYr * f,
  };
}

/**
 * A simulated taker fill: the price after half-spread and impact, and the fee
 * in quote currency. Prediction-market prices are probabilities and stay in (0, 1).
 */
export function paperFill(
  m: CostModel,
  side: "buy" | "sell",
  qty: number,
  price: number,
  prediction = false
): { price: number; fee: number; slippage: number } {
  const q = Math.abs(qty);
  const slip = slippageBps(m, q * price) / 10_000;
  let px = side === "buy" ? price * (1 + slip) : price * (1 - slip);
  if (prediction) px = Math.min(0.999, Math.max(0.001, px));
  return { price: px, fee: (px * q * m.takerBps) / 10_000, slippage: Math.abs(px - price) * q };
}

/** Gross, costs and net that always add up, with the 40 % flag. Mirrors `PnlBreakdown::new`. */
export function breakdown(gross: number, costs: number): PnlBreakdown {
  const c = Math.max(0, costs);
  const costShare = gross > 0 ? c / gross : undefined;
  const costHeavy = costShare !== undefined ? costShare > COST_HEAVY_SHARE : c > 0;
  return { gross, costs: c, net: gross - c, costShare, costHeavy };
}
