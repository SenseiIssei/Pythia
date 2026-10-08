import type { CostVenue, LiveStatus, Venue } from "./types";

/** Every engine venue id under its proper name, the way the venue writes it. */
const NAMES: Record<string, string> = {
  kraken: "Kraken",
  binance: "Binance",
  bybit: "Bybit",
  okx: "OKX",
  coinbase: "Coinbase",
  alpaca: "Alpaca",
  polymarket: "Polymarket",
};

/** "kraken" becomes "Kraken", "okx" becomes "OKX". An unknown id is shown as it is. */
export function exchangeName(id: string | undefined | null): string {
  if (!id) return "";
  return NAMES[id.trim().toLowerCase()] ?? id;
}

type DemoLive = Pick<LiveStatus, "demoVenues" | "demoExchange" | "demoRealPrices">;

/**
 * Crypto demo orders go to an exchange whose demo account has its own
 * prices (OKX): a demo fill there proves the API path, not the price.
 */
export function demoIsApiTestOnly(live: DemoLive): boolean {
  return (live.demoVenues ?? []).includes("crypto") && !!live.demoExchange && live.demoRealPrices === false;
}

/** The sentence every page shows next to demo numbers on such an exchange. */
export function demoApiTestNote(live: DemoLive): string {
  const name = exchangeName(live.demoExchange);
  return `${name} runs its demo account on its own prices, which it does not document as the real market. Demo numbers on ${name} are an API test, not a price test.`;
}

/**
 * The exchange an autopilot started now trades on, as the engine wants it:
 * crypto demo goes to the exchange whose demo keys are saved, crypto paper
 * and live to the exchange selected in Settings, US shares to Alpaca.
 */
export function autopilotVenue(
  mode: "paper" | "demo" | "live",
  assetClass: Venue,
  live: DemoLive,
  cryptoCostVenue: CostVenue,
): CostVenue {
  if (assetClass !== "crypto") return assetClass === "polymarket" ? "polymarket" : "alpaca";
  if (mode === "demo" && (live.demoVenues ?? []).includes("crypto") && live.demoExchange) return live.demoExchange;
  return cryptoCostVenue;
}

/**
 * Where a crypto demo order goes, by name: the demo exchange, never the
 * asset class. `undefined` when no crypto demo keys are saved.
 */
export function cryptoDemoName(live: DemoLive): string | undefined {
  return (live.demoVenues ?? []).includes("crypto") && live.demoExchange ? exchangeName(live.demoExchange) : undefined;
}
