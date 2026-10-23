import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import {
  change24h,
  historyAmounts,
  historyFee,
  historyPrice,
  historyTitle,
  parseOnchainView,
  solscanAccount,
  totalChange24h,
  valueLine,
  walletState,
  type OnchainView,
} from "./onchainLive";
import { WalletBody, PumpfunCard } from "./pages/Wallet";
import { Quote } from "./pages/OnchainWallet";
import type { PumpfunView } from "./pumpfunLive";

/** Made-up addresses (base58, 32 characters), not real wallets. */
const ADDR = "11111111111111111111111111111111";
const PF_ADDR = "22222222222222222222222222222222";
const T = 1_792_450_000_000;
const H = 3_600_000;

/** The engine's answer for the Wallet tab as it serializes it (camelCase). */
function raw(status: Record<string, unknown> = {}, over: Record<string, unknown> = {}) {
  return {
    running: true,
    status: {
      t: T - 5_000, running: true, on: true, mode: "alpha", gate: [], address: ADDR, solLamports: 500_000_000,
      balances: [
        { coin: "SOL", symbol: "SOL", mint: "MintSo1", amount: 0.5, usd: 100, priceUsd: 200 },
        { coin: "USDC", symbol: "USDC", mint: "MintUsdc", amount: 30, usd: 30, priceUsd: 1 },
      ],
      totalUsd: 130,
      ack: { mode: "alpha", books: ["onchain_breakout_top10_live"], mints: ["SOL", "USDC"], maxTotalUsd: 100, maxTradeUsd: 25, maxDailyLossUsd: 25, maxConvertUsd: 50, expires: "2026-12-31" },
      hard: { maxTotalUsd: 100, maxTradeUsd: 25, maxDailyLossUsd: 25, maxConvertUsd: 100 },
      limits: { maxTotalUsd: 100, maxTradeUsd: 25, maxDailyLossUsd: 25, maxConvertUsd: 50 },
      coins: [
        { coin: "SOL", symbol: "SOL", mint: "MintSo1", decimals: 9, allowed: true },
        { coin: "USDC", symbol: "USDC", mint: "MintUsdc", decimals: 6, allowed: true },
      ],
      kill: false,
      stops: { daily: false, total: false },
      ...status,
    },
    address: ADDR,
    trades: [],
    converts: [],
    killFile: false,
    nowMs: T,
    eurUsd: { price: 1.25, open: 1.25, t: T },
    values: [
      { t: T - 2 * H, usd: 128, prices: { SOL: 196, USDC: 1 } },
      { t: T - 24 * H - 600_000, usd: 120, prices: { SOL: 160, USDC: 1 } },
      { t: T - 30 * H, usd: 110, prices: { SOL: 150 } },
      { t: "odd" },
    ],
    history: [
      { sig: "FakeDep", t: T - 30 * H, kind: "deposit", ok: true, ours: false, moves: [{ coin: "SOL", mint: "MintSo1", amount: 0.6 }], feeSol: 0 },
      { sig: "FakeSwap", t: T - 3 * H, kind: "swap", ok: true, ours: true, moves: [{ coin: "USDC", amount: -20 }, { coin: "SOL", amount: 0.1 }],
        from: "USDC", fromAmount: 20, to: "SOL", toAmount: 0.1, price: 200, feeSol: 0.000045, baseSol: 0.000005, prioritySol: 0.00004, tipSol: 0.000005, rentSol: 0 },
      { sig: "FakeFail", t: T - 4 * H, kind: "failed", ok: false, err: "Custom 6001", ours: true, moves: [], feeSol: 0.000085 },
      { sig: "Odd", kind: "teleport" },
    ],
    historyMs: T - 60_000,
    ...over,
  };
}

const view = (status: Record<string, unknown> = {}, over: Record<string, unknown> = {}): OnchainView => parseOnchainView(raw(status, over));

describe("the Wallet tab's data", () => {
  it("reads the value chart oldest first and the history newest first, dropping odd entries", () => {
    const v = view();
    expect(v.values.map((p) => p.t)).toEqual([T - 30 * H, T - 24 * H - 600_000, T - 2 * H]);
    expect(v.history.map((e) => e.sig)).toEqual(["FakeSwap", "FakeFail", "FakeDep"]);
    expect(v.historyMs).toBe(T - 60_000);
    expect(parseOnchainView({}).history).toEqual([]);
    expect(parseOnchainView({ values: "x" }).values).toEqual([]);
  });

  it("reads a quote's price impact, fee and slippage", () => {
    const v = view({}, { converts: [{ id: "c1792449990002-0002", state: "proposed", from: "USDC", to: "SOL", amount: 10, priceImpactPct: 0.012, feeSol: 0.000355, slippageBps: 30, route: [] }] });
    expect(v.converts[0]).toMatchObject({ priceImpactPct: 0.012, feeSol: 0.000355, slippageBps: 30 });
  });

  it("says the gate's state in plain words: alpha, test, locked", () => {
    expect(walletState(view())).toMatchObject({ mode: "alpha", alpha: true, label: "Alpha" });
    expect(walletState(view()).words).toContain("At most $25.00 a swap, $100.00 in the wallet, $25.00 loss a day.");
    expect(walletState(view({ mode: "test", ack: { mode: "test" } }))).toMatchObject({ mode: "test", label: "Test" });
    expect(walletState(view({ on: false }))).toMatchObject({ mode: "locked", alpha: true, label: "Locked (Alpha phase set up)" });
    expect(walletState(view({}, { killFile: true }))).toMatchObject({ mode: "locked", tone: "bad" });
    expect(walletState(parseOnchainView({ running: false }))).toMatchObject({ mode: "locked", alpha: false, label: "Locked" });
  });

  it("draws the value line with the total right now and finds the 24 h change", () => {
    const v = view();
    expect(valueLine(v).map((p) => p.usd)).toEqual([110, 120, 128, 130]);
    expect(change24h(v, "SOL")).toBeCloseTo(200 / 160 - 1);
    expect(change24h(v, "USDC")).toBe(0);
    expect(change24h(view({}, { values: [] }), "SOL")).toBeNull();
    expect(totalChange24h(v)).toBe(10);
  });

  it("words each movement, its price, its fee and its amounts", () => {
    const [swap, fail, dep] = view().history;
    expect(historyTitle(dep)).toBe("Received 0.6 SOL");
    expect(historyTitle(swap)).toBe("Swapped 20 USDC to 0.1 SOL");
    expect(historyTitle(fail)).toBe("Failed transaction");
    expect(historyPrice(swap)).toBe("1 SOL = 200 USDC");
    expect(historyPrice({ kind: "swap", from: "SOL", to: "USDC", price: 199.5 })).toBe("1 SOL = 199.5 USDC");
    expect(historyPrice(dep)).toBeNull();
    expect(historyFee(swap)).toBe("fee 0.000045 SOL (priority 0.00004, tip 0.000005)");
    expect(historyFee(dep)).toBeNull();
    expect(historyAmounts(swap)).toEqual(["+0.1 SOL", "-20 USDC"]);
    expect(solscanAccount(ADDR)).toBe(`https://solscan.io/account/${ADDR}`);
  });
});

const PF = { running: true, address: PF_ADDR, status: { address: PF_ADDR, balanceSol: 0.75 }, solEur: { price: 160, open: 160, t: T } } as unknown as PumpfunView;

describe("the Wallet tab", () => {
  const html = renderToStaticMarkup(<WalletBody v={view()} offset={0} onChanged={() => {}} pf={PF} pfErr={null} embedded={false} />);

  it("shows the worth, Alpha clearly, the assets with their 24 h change and where to send SOL", () => {
    expect(html).toContain("Alpha phase");
    expect(html).toContain("€104.00");                 // 130 USD at 1.25
    expect(html).toContain("$130.00");
    expect(html).toContain("+25.00%");                 // SOL from 160 to 200
    expect(html).toContain("Send SOL here");
    expect(html).toContain(ADDR);
    expect(html).toContain("QR code of the wallet address");
    expect(html).toContain("Copy address");
  });

  it("lists every movement with its Solscan link, the swap, the pump.fun wallet and the kill switch", () => {
    expect(html).toContain("Swapped 20 USDC to 0.1 SOL");
    expect(html).toContain("Received 0.6 SOL");
    expect(html).toContain("Failed transaction");
    expect(html).toContain("https://solscan.io/tx/FakeSwap");
    expect(html).toContain("1 SOL = 200 USDC");
    expect(html).toContain("Get quote");
    expect(html).toContain("pump.fun bot&#x27;s wallet");
    expect(html).toContain("0.7500 SOL");
    expect(html).toContain("Stop trading now");
  });

  it("has no way to send money out, and says how to withdraw", () => {
    expect(html).toContain("How to withdraw");
    expect(html).toContain("import the wallet&#x27;s backup into Phantom");
    expect(html).not.toMatch(/>\s*(Send|Withdraw)\s*</);
  });

  it("says when the history was not read yet, and shows a locked wallet without the Alpha notice", () => {
    const locked = renderToStaticMarkup(<WalletBody v={view({ on: false, mode: "test", ack: { mode: "test" } }, { history: [], historyMs: null })} offset={0} onChanged={() => {}} pf={null} pfErr="no server" embedded />);
    expect(locked).toContain("Locked");
    expect(locked).not.toContain("Alpha phase");
    expect(locked).toContain("The history job reads the chain every 5 minutes");
    expect(locked).toContain("no server");
  });

  it("previews a quote with price impact, fee, minimum received and the countdown", () => {
    const q = view({}, { converts: [{ id: "c1792449990002-0002", state: "proposed", from: "USDC", to: "SOL", amount: 10, expectedOut: 0.05, minOut: 0.0498, costBps: 4.2, inUsd: 10, route: ["Whirlpool"], priceImpactPct: 0.012, feeSol: 0.000355, slippageBps: 30, expiresMs: T + 40_000 }] }).converts[0];
    const out = renderToStaticMarkup(<Quote c={q} left={40} over={false} err={null} busy={false} onConfirm={() => {}} />);
    for (const s of ["Minimum received", "0.0498 SOL", "slippage 30 bps", "Price impact", "1.200 %", "at most 0.000355 SOL", "40 s left", "Confirm"]) expect(out).toContain(s);
  });

  it("links the embedded pump.fun card to the whole app", () => {
    const out = renderToStaticMarkup(<PumpfunCard v={PF} err={null} embedded />);
    expect(out).toContain("?page=pumpfun");
    expect(out).toContain(`https://solscan.io/account/${PF_ADDR}`);
  });
});
