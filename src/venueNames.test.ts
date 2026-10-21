import { describe, expect, it } from "vitest";
import { autopilotVenue, cryptoDemoName, demoApiTestNote, demoIsApiTestOnly, exchangeName } from "./venueNames";

describe("autopilotVenue", () => {
  const live = { demoVenues: ["crypto" as const], demoExchange: "bybit" as const, demoRealPrices: true };

  it("sends a crypto demo autopilot to the demo exchange, not the live one", () => {
    expect(autopilotVenue("demo", "crypto", live, "kraken")).toBe("bybit");
    expect(exchangeName(autopilotVenue("demo", "crypto", live, "kraken"))).toBe("Bybit");
  });

  it("keeps paper and live crypto on the exchange selected in Settings, and shares on Alpaca", () => {
    expect(autopilotVenue("paper", "crypto", live, "kraken")).toBe("kraken");
    expect(autopilotVenue("live", "crypto", live, "kraken")).toBe("kraken");
    expect(autopilotVenue("demo", "alpaca", live, "kraken")).toBe("alpaca");
  });

  it("sends a crypto demo autopilot to Alpaca when crypto demo runs on the Alpaca paper account", () => {
    const alp = { demoVenues: ["crypto" as const, "alpaca" as const], demoExchange: "alpaca" as const, demoRealPrices: true };
    expect(autopilotVenue("demo", "crypto", alp, "kraken")).toBe("alpaca");
    expect(cryptoDemoName(alp)).toBe("Alpaca");
    expect(demoIsApiTestOnly(alp)).toBe(false);
  });

  it("falls back to the selected exchange when no demo keys are saved", () => {
    expect(autopilotVenue("demo", "crypto", { demoVenues: [] }, "okx")).toBe("okx");
  });

  it("puts perps on the perps venue the server follows, Kraken Futures when it says nothing", () => {
    const perps = { exchange: "bybit_perps" as const, label: "Bybit perps", demoReady: true, listed: 400, markets: 20, tickersAt: 0, accountAt: 0, fundingTotal: 0, longs: 0, shorts: 0, live: "" };
    expect(autopilotVenue("demo", "perps", { demoVenues: ["perps"], perps }, "kraken")).toBe("bybit_perps");
    expect(autopilotVenue("paper", "perps", { demoVenues: [] }, "kraken")).toBe("kraken_futures");
    expect(exchangeName("kraken_futures")).toBe("Kraken Futures");
  });
});

describe("exchangeName", () => {
  it("shows the exchange's own name, not the engine id", () => {
    expect(exchangeName("kraken")).toBe("Kraken");
    expect(exchangeName("okx")).toBe("OKX");
    expect(exchangeName("bybit")).toBe("Bybit");
    expect(exchangeName("alpaca")).toBe("Alpaca");
  });

  it("passes an unknown id through and an empty one as nothing", () => {
    expect(exchangeName("mtgox")).toBe("mtgox");
    expect(exchangeName(undefined)).toBe("");
  });
});

describe("demo on an exchange with its own prices", () => {
  it("is an API test only when the crypto demo exchange says its prices are not real", () => {
    expect(demoIsApiTestOnly({ demoVenues: ["crypto"], demoExchange: "okx", demoRealPrices: false })).toBe(true);
    expect(demoIsApiTestOnly({ demoVenues: ["crypto"], demoExchange: "bybit", demoRealPrices: true })).toBe(false);
    // No crypto demo keys: nothing to warn about.
    expect(demoIsApiTestOnly({ demoVenues: ["alpaca"], demoRealPrices: false })).toBe(false);
  });

  it("says so in a plain sentence that names the exchange", () => {
    const note = demoApiTestNote({ demoVenues: ["crypto"], demoExchange: "okx", demoRealPrices: false });
    expect(note).toContain("OKX");
    expect(note).toContain("an API test, not a price test");
  });

  it("names the demo exchange, never the asset class", () => {
    expect(cryptoDemoName({ demoVenues: ["crypto"], demoExchange: "bybit" })).toBe("Bybit");
    expect(cryptoDemoName({ demoVenues: [], demoExchange: "bybit" })).toBeUndefined();
  });
});
