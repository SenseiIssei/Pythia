// Maker execution, as the UI shows it. See docs/DEMO.md ("Maker orders on the
// Alpaca crypto demo route").

import type { LiveStatus, MakerSettings, Order } from "../types";

/** The route key of crypto demo orders on the Alpaca paper account. */
export const ALPACA_CRYPTO_DEMO = "demo:alpaca:crypto";

/** The Alpaca crypto demo route's setting, when the backend reports one. */
export function alpacaMaker(live: LiveStatus): MakerSettings | undefined {
  return live.makerRoutes?.[ALPACA_CRYPTO_DEMO];
}

/** One line on how the route works its orders. */
export function makerSummary(s: MakerSettings | undefined): string {
  if (!s) return "market orders";
  if (!s.enabled) return "market orders (maker execution off)";
  return `maker limits at the touch, re-priced every ${s.restSec}s, ${s.maxTries} ${
    s.maxTries === 1 ? "try" : "tries"
  }, then a marketable limit up to ${s.fallbackBandBps} bps past the touch`;
}

/** "80% maker" for a maker-route order with fills, else null. */
export function makerShare(o: Pick<Order, "makerQty" | "takerQty">): string | null {
  const maker = o.makerQty ?? 0;
  const total = maker + (o.takerQty ?? 0);
  if (o.makerQty === undefined || total <= 0) return null;
  return `${Math.round((maker / total) * 100)}% maker`;
}
