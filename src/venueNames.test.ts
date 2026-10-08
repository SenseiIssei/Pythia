import { describe, expect, it } from "vitest";
import { cryptoDemoName, demoApiTestNote, demoIsApiTestOnly, exchangeName } from "./venueNames";

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
