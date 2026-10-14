// Maker execution, as the UI shows it. See docs/DEMO.md ("Maker orders on the
// Alpaca crypto demo route").

import type { LiveStatus, MakerRouteStats, MakerSettings, MakerWindow, Order } from "../types";

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

/** The Alpaca crypto demo route's statistics, when there are any. */
export function alpacaMakerStats(live: LiveStatus): MakerRouteStats | undefined {
  return live.makerStats?.find((s) => s.route === ALPACA_CRYPTO_DEMO);
}

const pct = (x: number) => `${Math.round(x * 100)}%`;

/** One short line for a window: "7d: 12 orders, 83% maker by qty (75% of orders), rests 41s, cost 16.2 vs 27.0 bps, 2 fallbacks". */
export function makerWindowLine(w: MakerWindow): string {
  const head = `${w.days}d: `;
  if (w.orders === 0) return `${head}no maker orders yet`;
  const parts = [`${w.orders} ${w.orders === 1 ? "order" : "orders"}`];
  if (w.makerFillRateQty !== undefined) {
    const byOrder = w.makerFillRateOrders !== undefined ? ` (${pct(w.makerFillRateOrders)} of orders)` : "";
    parts.push(`${pct(w.makerFillRateQty)} maker by qty${byOrder}`);
  }
  if (w.avgRestSec !== undefined) parts.push(`rests ${Math.round(w.avgRestSec)}s`);
  if (w.realisedBps !== undefined && w.modelledBps !== undefined) {
    parts.push(`cost ${w.realisedBps.toFixed(1)} vs ${w.modelledBps.toFixed(1)} bps modelled`);
  }
  const noBook = w.noBookFallbacks > 0 ? ` (${w.noBookFallbacks} without a book)` : "";
  parts.push(`${w.fallbacks} ${w.fallbacks === 1 ? "fallback" : "fallbacks"}${noBook}`);
  return head + parts.join(", ");
}
