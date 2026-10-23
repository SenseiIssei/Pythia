import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import {
  ageText,
  badgeUi,
  changeText,
  directImage,
  imageOfMetadata,
  isStale,
  parseTrends,
  solText,
  updatedClock,
  usdShort,
  type TrendsView,
} from "./trends";
import { TrendsBody, type TrendTab } from "./pages/Trends";
import { readDeepLink } from "./deepLink";

const NOW = 1_792_450_000_000;
/** Made-up mints (base58, 32 characters), not real coins. */
const M1 = "11111111111111111111111111111111";
const M2 = "22222222222222222222222222222222";
const M3 = "33333333333333333333333333333333";

function coin(mint: string, over: Record<string, unknown> = {}) {
  return {
    mint, name: "Test Coin", symbol: "TST", uri: "https://ipfs.io/ipfs/x", created_ms: NOW - 600_000, age_s: 600,
    vol_1m: 1.2, vol_5m: 12.5, vol_15m: 30, sell_5m: 4, net_5m: 8.5, buys_5m: 40, sells_5m: 12, buyers_5m: 33,
    chg_5m: 0.23, chg_15m: -0.08, price_sol: 5e-8, mcap_sol: 50, mcap_usd: 9100, progress: 0.42, migrated: false,
    complete_ms: null, migrate_ms: null, speed_pm: 0.03, pool_vol_5m: 0, pool_trades_5m: 0, spark: [40, 45, 50],
    smart_n: 3, creator_migrated: 1, creator_coins: 4, dev_sold: 0.1, flags: [], blocked: false,
    p_win: null, p_rug: null, p_3x: 0.12, base_win: null, base_rug: null, base_3x: 0.05, win_label: null,
    badges: ["p3x_high", "smart", "creator_mig"],
    ...over,
  };
}

function raw(over: Record<string, unknown> = {}, dex: unknown = undefined) {
  return {
    trends: {
      t: NOW - 2_000, written_ms: NOW - 5_000, bucket_s: 30, sol_usd: 182.5, tracked: 412,
      lists: {
        hot: [coin(M1), coin(M2, { blocked: true, flags: ["mayhem"], badges: ["smart"], name: "Bad" }), { name: "no mint" }],
        migrating: [coin(M3, { progress: 0.91, speed_pm: 0.05 })],
        fresh: [coin(M3, { migrated: true, progress: null, migrate_ms: NOW - 240_000, pool_vol_5m: 7.25, pool_trades_5m: 18,
                           p_win: 0.41, base_win: 0.25, p_rug: 0.5, base_rug: 0.3, p_3x: null, badges: ["win_high", "rug_risk"] })],
      },
      models: { win: true, rug: true, p3x: true },
      badges: { smart: "2 or more early buyers with a record", rug_risk: "P(rug) at or above 1.5x" },
      note: "Signals, not advice.",
      ...over,
    },
    dexscreener: dex === undefined ? {
      updatedMs: NOW - 600_000, status: "ok", caveat: "High risk, watch only.",
      items: [
        { chain: "solana", address: M1, symbol: "CAT", name: "Cyber Cat", dex: "pumpswap", change_h1: -21.4, change_h24: 157, volume_h24: 636366,
          liquidity_usd: 7760, fdv: 11143, age_h: 18.7, pair_url: "https://dexscreener.com/solana/pair", flags: ["thin liquidity"] },
        { symbol: "no address" },
      ],
    } : dex,
  };
}

const view = (over: Record<string, unknown> = {}, dex?: unknown): TrendsView => parseTrends(raw(over, dex));

describe("the Trends data", () => {
  it("reads the three lists and the DexScreener list, dropping entries without a mint", () => {
    const v = view();
    expect(v.lists.hot.map((c) => c.mint)).toEqual([M1, M2]);
    expect(v.lists.migrating[0].progress).toBe(0.91);
    expect(v.lists.fresh[0].migrated).toBe(true);
    expect(v.lists.fresh[0].poolVol5m).toBe(7.25);
    expect(v.solUsd).toBe(182.5);
    expect(v.present).toBe(true);
    expect(v.dex?.items.map((d) => d.symbol)).toEqual(["CAT"]);
    expect(v.dex?.items[0].pairUrl).toBe("https://dexscreener.com/solana/pair");
  });

  it("answers an empty server without throwing", () => {
    const v = parseTrends({ trends: null, dexscreener: null });
    expect(v.present).toBe(false);
    expect(v.lists).toEqual({ hot: [], migrating: [], fresh: [] });
    expect(v.dex).toBeNull();
    expect(parseTrends(null).present).toBe(false);
    expect(parseTrends({ trends: { lists: { hot: "x" } } }).lists.hot).toEqual([]);
  });

  it("never highlights a blocked coin, whatever the file says", () => {
    const bad = view().lists.hot[1];
    expect(bad.blocked).toBe(true);
    expect(bad.badges).toEqual([]);
    expect(badgeUi(bad)).toEqual([]);
  });

  it("names the badges with their numbers and adds the lab's rule", () => {
    const v = view();
    const b = badgeUi(v.lists.hot[0], v.badges);
    expect(b.map((x) => x.label)).toEqual(["P(3x) 12 %", "3 smart buyers", "Creator: 1 migrated"]);
    expect(b.find((x) => x.id === "smart")?.why).toContain("Rule: 2 or more early buyers with a record.");
    const f = badgeUi(v.lists.fresh[0], v.badges);
    expect(f.map((x) => [x.label, x.tone])).toEqual([["P(win) 41 %", "good"], ["Rug risk 50 %", "bad"]]);
    expect(badgeUi({ ...v.lists.hot[0], badges: ["unknown"] })).toEqual([]);
  });

  it("only takes https or ipfs images", () => {
    expect(directImage("https://x.io/a.png")).toBe("https://x.io/a.png");
    expect(directImage("ipfs://Qm1/a.webp")).toBe("https://ipfs.io/ipfs/Qm1/a.webp");
    expect(directImage("https://metadata.example/abc")).toBeNull();
    expect(directImage("http://x.io/a.png")).toBeNull();
    expect(imageOfMetadata({ image: "ipfs://Qm2" })).toBe("https://ipfs.io/ipfs/Qm2");
    expect(imageOfMetadata({ image: "javascript:alert(1)" })).toBeNull();
    expect(imageOfMetadata("x")).toBeNull();
  });

  it("formats the numbers a row shows", () => {
    expect(changeText(0.234)).toBe("+23 %");
    expect(changeText(-0.085)).toBe("-8.5 %");
    expect(changeText(null)).toBe("n/a");
    expect(solText(12.34)).toBe("12.3 SOL");
    expect(solText(0.456)).toBe("0.46 SOL");
    expect(usdShort(9100)).toBe("$9.1k");
    expect(usdShort(1_250_000)).toBe("$1.3M");
    expect(ageText(45)).toBe("45 s");
    expect(ageText(720)).toBe("12 min");
    expect(updatedClock(new Date(2026, 9, 23, 14, 5, 9).getTime())).toBe("updated 14:05:09");
    expect(updatedClock(null)).toBe("");
  });

  it("calls a file older than 90 s not current", () => {
    expect(isStale(view(), NOW)).toBe(false);
    expect(isStale(view({ written_ms: NOW - 120_000 }), NOW)).toBe(true);
    expect(isStale(view({ written_ms: null }), NOW)).toBe(true);
  });

  it("opens as ?page=trends, embedded with &embed=1", () => {
    expect(readDeepLink("?page=trends&embed=1")).toEqual({ page: "trends", embed: true });
    expect(readDeepLink("?page=Trends")).toEqual({ page: "trends", embed: false });
  });
});

const render = (v: TrendsView, tab: TrendTab) => renderToStaticMarkup(<TrendsBody v={v} tab={tab} onTab={() => {}} nowMs={NOW} />);

describe("the Trends page", () => {
  it("shows the honest note, the four tabs and the hot rows with links and badges", () => {
    const html = render(view(), "hot");
    expect(html).toContain("Signals, not advice");
    expect(html).toContain("no rule that wins reliably");
    for (const t of ["Hot now", "About to migrate", "Fresh pools", "DexScreener"]) expect(html).toContain(t);
    expect(html).toContain(`https://dexscreener.com/solana/${M1}`);
    expect(html).toContain(`https://solscan.io/token/${M1}`);
    expect(html).toContain('data-badge="smart"');
    expect(html).toContain("12.5 SOL");
    expect(html).toContain("$9.1k cap");
    expect(html).toContain("33 buyers");
    expect(html).toContain("+23 % 5 min");
    expect(html).toContain('aria-valuenow="42"');
    expect(html).toContain("1 SOL = $182.50 (Kraken)");
    expect(html).not.toContain("\u2014");
  });

  it("dims a blocked coin and gives it no badge", () => {
    const html = render(view(), "hot");
    const row = html.slice(html.indexOf(`data-mint="${M2}"`));
    const end = row.indexOf("</li>");
    const one = row.slice(0, end);
    expect(one).toContain("blocked");
    expect(one).toContain("Mayhem mode");
    expect(one).not.toContain("data-badge");
    expect(html).toContain('class="py-3 opacity-60"');
  });

  it("shows progress and speed for curves about to migrate, pool activity for fresh pools", () => {
    const mig = render(view(), "migrating");
    expect(mig).toContain("91.0 %");
    expect(mig).toContain("+5.0 pts/min");
    const fresh = render(view(), "fresh");
    expect(fresh).toContain("7.25 SOL");
    expect(fresh).toContain("18 pool trades, 5 min");
    expect(fresh).toContain("migrated 4 min ago");
    expect(fresh).toContain("P(win) 41 %");
  });

  it("shows the DexScreener list with its flags", () => {
    const html = render(view(), "dex");
    expect(html).toContain("Cyber Cat");
    expect(html).toContain("thin liquidity");
    expect(html).toContain("-21 % 1 h");
    expect(html).toContain("+157 % 24 h");
    expect(html).toContain("https://dexscreener.com/solana/pair");
    expect(render(view({}, null), "dex")).toContain("No DexScreener list");
  });

  it("says when there is nothing yet, and when the file is old", () => {
    const empty = parseTrends({ trends: null, dexscreener: null });
    expect(render(empty, "hot")).toContain("No trends yet");
    expect(render(view({ written_ms: NOW - 300_000 }), "hot")).toContain("Not current");
    expect(render(view({ lists: { hot: [], migrating: [], fresh: [] } }), "migrating")).toContain("No curve is above 70 %");
  });
});
