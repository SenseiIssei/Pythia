import type { DataHealth, DataKind, FeedSource, KindHealth } from "./types";

// Plain-language reading of the engine's `dataHealth` section, shared by the
// header indicator and the Live page card. Pure, so it is tested without React.

export const SOURCE_LABEL: Record<FeedSource, string> = {
  "kraken-ws": "Kraken stream",
  kraken: "Kraken",
  binance: "Binance",
  "binance-vision": "Binance mirror",
  coinbase: "Coinbase",
  bybit: "Bybit",
  okx: "OKX",
};

export const KIND_LABEL: Record<DataKind, string> = {
  quotes: "Quotes",
  candles: "Candles",
  books: "Order books",
};

/** The exchange behind a source: the stream and REST Kraken are one venue. */
export function venueOf(s: FeedSource): string {
  if (s === "kraken-ws") return "kraken";
  if (s === "binance-vision") return "binance";
  return s;
}

export function sourceLabel(s?: FeedSource | null): string {
  return s ? SOURCE_LABEL[s] ?? s : "none";
}

/** 7 s, 4 min, 2 h. */
export function fmtAge(sec?: number | null): string {
  if (sec == null || !Number.isFinite(sec)) return "never";
  if (sec < 60) return `${Math.round(sec)} s`;
  if (sec < 3600) return `${Math.round(sec / 60)} min`;
  return `${Math.round(sec / 3600)} h`;
}

export function kindOf(h: DataHealth, kind: DataKind): KindHealth | undefined {
  return h.kinds.find((k) => k.kind === kind);
}

/** On another exchange than the first choice (a REST fallback of the same
 *  venue is not a failover worth a warning). */
export function onFallback(k: KindHealth): boolean {
  return !!k.active && !!k.primary && venueOf(k.active) !== venueOf(k.primary);
}

export interface DataStatus {
  tone: "green" | "amber" | "red";
  label: string;
  detail: string;
}

/** The one-badge summary for the header, or null where no feeds run. */
export function dataStatus(h: DataHealth | null | undefined): DataStatus | null {
  if (!h || !h.running) return null;
  const quotes = kindOf(h, "quotes");
  const candles = kindOf(h, "candles");
  const books = kindOf(h, "books");
  const where = [quotes, candles]
    .filter((k): k is KindHealth => !!k)
    .map((k) => `${KIND_LABEL[k.kind].toLowerCase()} on ${sourceLabel(k.active)} (${fmtAge(k.lastUpdateAgeSec)} old)`)
    .join(", ");

  if (!h.ok) {
    const parts = [quotes, candles]
      .filter((k): k is KindHealth => !!k && k.stale.length > 0)
      .map((k) => `${KIND_LABEL[k.kind].toLowerCase()} stale for ${k.stale.length} of ${k.markets} markets`);
    return {
      tone: "red",
      label: "DATA STALE",
      detail: `${parts.join(", ")}. New entries are refused and stops wait for a fresh price.`,
    };
  }
  const fallback = [quotes, candles, books].filter((k): k is KindHealth => !!k && onFallback(k));
  const suspect = h.markets.filter((m) => m.suspect).length;
  if (fallback.length > 0) {
    return {
      tone: "amber",
      label: "DATA FAILOVER",
      detail: `${fallback.map((k) => `${KIND_LABEL[k.kind]} on ${sourceLabel(k.active)}, not ${sourceLabel(k.primary)}`).join("; ")}. Fresh, from a fallback venue.`,
    };
  }
  if (suspect > 0) {
    return {
      tone: "amber",
      label: "DATA CHECK",
      detail: `${suspect} market(s) have a refused quote; the last good price stays the mark. ${where}.`,
    };
  }
  if (books && books.sources.length > 0 && books.stale.length > 0) {
    return {
      tone: "amber",
      label: "DATA",
      detail: `${where}. Order books stale for ${books.stale.length} markets: fills use the calibrated costs.`,
    };
  }
  return { tone: "green", label: "DATA", detail: `Live: ${where}.` };
}
