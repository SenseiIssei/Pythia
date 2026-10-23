import { afterEach, describe, expect, it, vi } from "vitest";
import {
  FAST_POLL_MS,
  SLOW_POLL_MS,
  allowedCoins,
  amountText,
  balanceMoney,
  checkConvert,
  gateReasons,
  onOff,
  onchainConfirm,
  onchainConvert,
  onchainKill,
  onchainLive,
  parseOnchainView,
  pollMs,
  priceOf,
  secondsLeft,
  totalMoney,
  type OnchainView,
} from "./onchainLive";

/** A made-up address (base58, 32 characters), not a real wallet. */
const ADDR = "11111111111111111111111111111111";
const T = 1_792_450_000_000;

/** The engine's answer as it serializes it (camelCase). */
function raw(over: Record<string, unknown> = {}, status: Record<string, unknown> = {}) {
  return {
    running: true,
    status: {
      t: T - 5_000, running: true, on: false, mode: "test",
      gate: ["the proof gate has not passed", "no simulate within 24 h"],
      address: ADDR, solLamports: 1_500_000_000,
      balances: [
        { coin: "SOL", symbol: "SOL", mint: "MintSo1", amount: 1.5, usd: 225, priceUsd: 150 },
        { coin: "USDC", symbol: "USDC", mint: "MintUsdc", amount: 20, usd: null, priceUsd: 1 },
      ],
      totalUsd: 245,
      day: { startUsd: 240, pnlUsd: 5, swaps: 0, converts: 1, convertUsd: 10 },
      ack: { mode: "test", books: ["onchain_breakout_top10_live"], mints: ["SOL", "USDC"], bookUsd: 150, maxTotalUsd: 200, maxTradeUsd: 100, maxDailyLossUsd: 30, maxConvertUsd: 100, expires: "2026-12-31", onKill: "hold" },
      hard: { maxTotalUsd: 500, maxTradeUsd: 100, maxDailyLossUsd: 100, maxConvertUsd: 250, reserveSol: 0.02, maxConverts: 10, confirmS: 60 },
      limits: { maxTotalUsd: 200, maxTradeUsd: 100, maxDailyLossUsd: 30, maxConvertUsd: 100 },
      coins: [
        { coin: "SOL", symbol: "SOL", mint: "MintSo1", decimals: 9, allowed: true },
        { coin: "USDC", symbol: "USDC", mint: "MintUsdc", decimals: 6, allowed: true },
        { coin: "BONK", symbol: "BONK", mint: "MintBonk", decimals: 5, allowed: false },
      ],
      kill: false,
      simulate: { t: T, ok: true },
      books: [{ book: "onchain_breakout_top10_live", allowed: false, why: "paper first" }],
      reconcile: { t: T, ok: true, diffs: [] },
      stops: { daily: false, total: false },
      ...status,
    },
    address: ADDR,
    trades: [{ t: T, kind: "convert", book: null, from: "USDC", to: "SOL", inAmount: 10, outAmount: 0.066, inUsd: 10, outUsd: 9.98, feeSol: 0.00004, sig: "FakeSig1", status: "filled", why: null }],
    converts: [
      { id: "c1792449990002-0002", state: "proposed", from: "USDC", to: "SOL", amount: 10, requestedMs: T - 5_000, expectedOut: 0.0667, minOut: 0.0663, costBps: 4.2, inUsd: 10, route: ["Whirlpool"], proposedMs: T - 4_000, expiresMs: T + 30_000, confirmedMs: null, doneMs: null, sig: null, outAmount: null, why: null },
      { id: "c1792449990001-0001", state: "filled", from: "SOL", to: "USDC", amount: 0.1, route: [], sig: "FakeSig2", outAmount: 15 },
    ],
    killFile: false,
    nowMs: T,
    eurUsd: { price: 1.08, open: 1.07, t: T },
    ...over,
  };
}

const view = (over: Record<string, unknown> = {}, status: Record<string, unknown> = {}): OnchainView => parseOnchainView(raw(over, status));

describe("parseOnchainView", () => {
  it("reads the engine's answer", () => {
    const v = view();
    expect(v.running).toBe(true);
    expect(v.address).toBe(ADDR);
    expect(v.status?.balances.map((b) => b.coin)).toEqual(["SOL", "USDC"]);
    expect(v.status?.limits?.maxTradeUsd).toBe(100);
    expect(v.status?.ack?.books).toEqual(["onchain_breakout_top10_live"]);
    expect(v.status?.hard?.reserveSol).toBe(0.02);
    expect(v.trades[0].feeSol).toBe(0.00004);
    expect(v.converts.map((c) => c.state)).toEqual(["proposed", "filled"]);
    expect(v.converts[0].route).toEqual(["Whirlpool"]);
    expect(v.converts[1].expectedOut).toBeNull();
    expect(v.eurUsd?.price).toBe(1.08);
  });

  it("turns anything malformed into null or empty and never throws", () => {
    for (const x of [null, undefined, "nope", 3, [], { status: "x", trades: "x", converts: {} }]) {
      const v = parseOnchainView(x);
      expect(v.status).toBeNull();
      expect(v.trades).toEqual([]);
      expect(v.converts).toEqual([]);
      expect(v.running).toBe(false);
      expect(v.eurUsd).toBeNull();
    }
    const v = parseOnchainView(
      raw(
        {
          converts: [{ id: "c1792449990003-0003", state: "teleported" }, { state: "filled" }, null, 7, { id: "c1792449990004-0004", state: "waiting", amount: "10", route: "x" }],
          trades: [null, { t: "soon", inAmount: "1" }],
          eurUsd: { price: 0 },
          killFile: "yes",
        },
        { balances: [{ amount: 1 }, { coin: "SOL", amount: "1.5" }], gate: ["a", 3, null], stops: null, day: "x", coins: "x" },
      ),
    );
    expect(v.converts).toHaveLength(1);
    expect(v.converts[0]).toMatchObject({ state: "waiting", amount: null, route: [] });
    expect(v.trades).toHaveLength(1);
    expect(v.trades[0]).toMatchObject({ t: null, inAmount: null });
    expect(v.eurUsd).toBeNull();
    expect(v.killFile).toBe(false);
    expect(v.status?.balances).toEqual([{ coin: "SOL", symbol: null, mint: null, amount: null, usd: null, priceUsd: null }]);
    expect(v.status?.gate).toEqual(["a"]);
    expect(v.status?.stops).toEqual({ daily: false, total: false });
    expect(v.status?.day).toBeNull();
    expect(v.status?.coins).toEqual([]);
    // A status without a time is no status.
    expect(view({}, { t: null }).status).toBeNull();
  });
});

describe("money", () => {
  it("gives each balance in dollars and in euro at EUR/USD (dollars per euro)", () => {
    const v = view();
    const [sol, usdc] = v.status!.balances;
    expect(balanceMoney(sol, v.eurUsd)).toEqual({ usd: 225, eur: 225 / 1.08 });
    // Without the trader's dollar figure: amount times price.
    expect(balanceMoney(usdc, v.eurUsd)).toEqual({ usd: 20, eur: 20 / 1.08 });
    expect(balanceMoney(sol, null)).toEqual({ usd: 225, eur: null });
    expect(balanceMoney({ ...sol, usd: null, priceUsd: null }, v.eurUsd)).toEqual({ usd: null, eur: null });
  });

  it("totals the wallet: the trader's total, else the sum of what it priced", () => {
    const v = view();
    expect(totalMoney(v.status, v.eurUsd)).toEqual({ usd: 245, eur: 245 / 1.08 });
    expect(totalMoney({ ...v.status!, totalUsd: null }, null)).toEqual({ usd: 245, eur: null });
    expect(totalMoney(null, v.eurUsd)).toEqual({ usd: null, eur: null });
  });

  it("writes amounts without trailing zeros", () => {
    expect(amountText(0.05)).toBe("0.05");
    expect(amountText(1234.5)).toBe("1,234.5");
    expect(amountText(null)).toBe("n/a");
  });
});

describe("checkConvert", () => {
  const v = view();
  it("lets an allowed pair within the per-trade limit through", () => {
    expect(allowedCoins(v.status)).toEqual(["SOL", "USDC"]);
    expect(priceOf(v.status, "SOL")).toBe(150);
    expect(checkConvert({ from: "USDC", to: "SOL", amount: "10,5" }, v)).toEqual({ ask: { from: "USDC", to: "SOL", amount: 10.5 }, errors: [] });
    expect(checkConvert({ from: "SOL", to: "USDC", amount: "0.66" }, v).ask).not.toBeNull();
  });

  it("refuses the same coin, a coin not allowed, a bad amount, more than the limit", () => {
    const err = (from: string, to: string, amount: string) => checkConvert({ from, to, amount }, v).errors.join(" | ");
    expect(err("SOL", "SOL", "1")).toContain("different coins");
    expect(err("USDC", "BONK", "1")).toContain("BONK is not");
    expect(err("WIF", "SOL", "1")).toContain("WIF is not");
    expect(err("", "SOL", "1")).toContain("Choose both");
    for (const a of ["", "0", "-1", "abc", "Infinity"]) expect(err("USDC", "SOL", a)).toContain("positive number");
    expect(err("SOL", "USDC", "0.7")).toContain("At most $100.00 per trade");
    expect(checkConvert({ from: "SOL", to: "USDC", amount: "0.7" }, v).ask).toBeNull();
  });

  it("skips the limit when no price is known, and refuses while the trader is off or killed", () => {
    const noPrice = view({}, { balances: [] });
    expect(checkConvert({ from: "SOL", to: "USDC", amount: "100" }, noPrice).errors).toEqual([]);
    expect(checkConvert({ from: "USDC", to: "SOL", amount: "1" }, view({ running: false })).errors).toContain("The trader is not running.");
    expect(checkConvert({ from: "USDC", to: "SOL", amount: "1" }, view({ status: null })).errors).toContain("The trader is not running.");
    expect(checkConvert({ from: "USDC", to: "SOL", amount: "1" }, view({ killFile: true })).errors).toContain("The kill switch is on.");
  });
});

describe("the proposal's countdown and the polling", () => {
  it("counts the seconds left of a proposed conversion only", () => {
    expect(secondsLeft({ state: "proposed", expiresMs: T + 60_000 }, T)).toBe(60);
    expect(secondsLeft({ state: "proposed", expiresMs: T + 59_001 }, T)).toBe(60);
    expect(secondsLeft({ state: "proposed", expiresMs: T - 1 }, T)).toBe(0);
    expect(secondsLeft({ state: "confirmed", expiresMs: T + 60_000 }, T)).toBeNull();
    expect(secondsLeft({ state: "proposed", expiresMs: null }, T)).toBeNull();
  });

  it("reads every 3 s while a conversion is on its way, else every 15 s", () => {
    expect(pollMs(view())).toBe(FAST_POLL_MS);
    expect(pollMs(view({ converts: [{ id: "c1792449990001-0001", state: "waiting" }] }))).toBe(3_000);
    expect(pollMs(view({ converts: [{ id: "c1792449990001-0001", state: "filled" }] }))).toBe(SLOW_POLL_MS);
    expect(pollMs(null)).toBe(15_000);
  });
});

describe("gateReasons and onOff", () => {
  it("says the trader is locked until the owner arms it when there is no status", () => {
    const v = view({ status: null, running: false });
    expect(onOff(v)).toEqual({ label: "Not running, locked", level: "off" });
    expect(gateReasons(v).join(" ")).toContain("locked until the owner arms it");
  });

  it("lists the trader's own reasons, the stops and the kill file", () => {
    const v = view();
    expect(onOff(v).level).toBe("warn");
    expect(gateReasons(v)).toEqual(["the proof gate has not passed", "no simulate within 24 h"]);
    const stopped = view({ killFile: true }, { stops: { daily: true, total: false } });
    expect(onOff(stopped).level).toBe("bad");
    const r = gateReasons(stopped);
    expect(r[0]).toContain("reports/onchain_live/KILL");
    expect(r.some((x) => x.includes("daily loss stop"))).toBe(true);
    expect(gateReasons(view({ running: false })).join(" ")).toContain("more than two minutes old");
    expect(gateReasons(view({}, { gate: [] }))).toEqual(["The trader is off."]);
  });

  it("has nothing to say while it trades", () => {
    const v = view({}, { on: true, gate: [] });
    expect(onOff(v)).toEqual({ label: "Trading real money (test mode)", level: "ok" });
    expect(gateReasons(v)).toEqual([]);
  });
});

describe("the engine's routes", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("reads the view and posts the request, the confirm and the kill, nothing else", async () => {
    vi.stubEnv("VITE_PYTHIA_SERVER", "/api/pythia");
    const asked: { url: string; method: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", async (u: string, init?: RequestInit) => {
      asked.push({ url: String(u), method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : null });
      const url = String(u);
      const body = url.endsWith("/api/onchain/live") ? raw() : url.endsWith("/convert") ? { id: "c1792449990005-abcd" } : url.endsWith("/confirm") ? { id: "c1792449990005-abcd", confirmed: true } : { killFile: true, path: "reports/onchain_live/KILL", already: false };
      return new Response(JSON.stringify(body), { status: 200 });
    });
    expect((await onchainLive()).converts).toHaveLength(2);
    expect(await onchainConvert({ from: "USDC", to: "SOL", amount: 10 })).toEqual({ id: "c1792449990005-abcd" });
    expect((await onchainConfirm("c1792449990005-abcd")).confirmed).toBe(true);
    expect((await onchainKill()).killFile).toBe(true);
    expect(asked).toEqual([
      { url: "/api/pythia/api/onchain/live", method: "GET", body: null },
      { url: "/api/pythia/api/onchain/live/convert", method: "POST", body: { from: "USDC", to: "SOL", amount: 10 } },
      { url: "/api/pythia/api/onchain/live/convert/confirm", method: "POST", body: { id: "c1792449990005-abcd" } },
      { url: "/api/pythia/api/onchain/live/kill", method: "POST", body: null },
    ]);
  });

  it("passes the engine's refusal on as the error", async () => {
    vi.stubEnv("VITE_PYTHIA_SERVER", "/api/pythia");
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ error: "The proposal has expired; ask for a new quote." }), { status: 400 }));
    await expect(onchainConfirm("c1792449990005-abcd")).rejects.toThrow("expired");
  });

  it("needs the connected backend", async () => {
    vi.stubEnv("VITE_PYTHIA_SERVER", "");
    await expect(onchainLive()).rejects.toThrow("connected backend");
    await expect(onchainKill()).rejects.toThrow("connected backend");
  });
});
