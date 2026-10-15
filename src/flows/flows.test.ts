import { describe, expect, it } from "vitest";
import {
  CARE,
  amountProblem,
  cardModel,
  careOf,
  floorFor,
  parseAmount,
  roundShares,
  startConfig,
  statusWords,
  strategyShares,
  toneOf,
  totals,
  vsBtcText,
} from "./autopilotView";
import {
  dayLabel,
  daySummary,
  fromJournal,
  isEvent,
  parseFill,
  shortLine,
  timeline,
} from "./activity";
import {
  ALERT_LANGUAGES,
  alertTitle,
  countsLine,
  deliveryOf,
  destinationName,
  groupCategories,
  languageOf,
  muteText,
  plainText,
  quietLine,
  validHhmm,
} from "./alerts";
import type { AutopilotSleeveStatus, AutopilotStatus, JournalEntry, PositionView } from "../types";

function status(over: Partial<AutopilotStatus> = {}): AutopilotStatus {
  return {
    config: {
      id: "a",
      name: "A",
      mode: "paper",
      venue: "kraken",
      capitalUsd: 1000,
      sleeves: [],
      stop: { onTakeProfit: "stop" },
      flattenOnStop: true,
    },
    state: "running",
    stopReason: null,
    pausedReason: null,
    stoppedMs: null,
    targetEquity: null,
    openPositions: 0,
    lastAction: null,
    startedMs: 0,
    startCapital: 1000,
    equity: 1000,
    pnl: 0,
    pnlPct: 0,
    peakEquity: 1000,
    drawdownPct: 0,
    floorEquity: null,
    trades: 0,
    fees: 0,
    bySleeve: [],
    history: [],
    ...over,
  };
}

function sleeve(over: Partial<AutopilotSleeveStatus>): AutopilotSleeveStatus {
  return { strategyId: "s", name: "S", weight: 1, pnl: 0, trades: 0, why: "", markets: [], ...over };
}

function entry(over: Partial<JournalEntry>): JournalEntry {
  return { id: "j1", ts: 0, kind: "system", message: "", mode: "paper", ...over };
}

describe("roundShares", () => {
  it("adds up to exactly 100", () => {
    const r = roundShares([1, 1, 1]);
    expect(r.reduce((a, b) => a + b, 0)).toBe(100);
    expect(r.sort()).toEqual([33, 33, 34]);
  });
  it("normalises weights that do not add up to 1", () => {
    expect(roundShares([3, 1])).toEqual([75, 25]);
  });
  it("is all zero without any positive weight", () => {
    expect(roundShares([0, -1])).toEqual([0, 0]);
  });
});

describe("strategyShares", () => {
  it("lists running sleeves biggest first, leaving out dropped ones", () => {
    const s = status({
      bySleeve: [
        sleeve({ strategyId: "a", name: "Trend", weight: 0.4 }),
        sleeve({ strategyId: "b", name: "Breakout", weight: 0.6 }),
        sleeve({ strategyId: "c", name: "Old", weight: 0, dropped: true }),
      ],
    });
    expect(strategyShares(s).map((x) => [x.name, x.pct])).toEqual([
      ["Breakout", 60],
      ["Trend", 40],
    ]);
  });
  it("falls back to the configured sleeves with names", () => {
    const s = status();
    s.config.sleeves = [{ strategyId: "x", weight: 1 }];
    expect(strategyShares(s, { x: "Momentum" })).toEqual([{ id: "x", name: "Momentum", pct: 100, pnl: 0 }]);
  });
});

describe("statusWords", () => {
  it("says what a running autopilot holds", () => {
    expect(statusWords(status(), 2).line).toBe("Running. Holds 2 assets.");
    expect(statusWords(status(), 1).line).toBe("Running. Holds 1 asset.");
  });
  it("says why it waits in cash", () => {
    expect(statusWords(status({ waiting: "no trend yet." }), 0).line).toBe("Running, in cash: no trend yet.");
  });
  it("says paused and stopped plainly", () => {
    expect(statusWords(status({ state: "paused" }), 0)).toMatchObject({ label: "Paused", tone: "warn" });
    expect(statusWords(status({ state: "stopped", stopReason: "loss limit reached" }), 0).line).toBe("Stopped: loss limit reached.");
    expect(statusWords(status({ state: "finished" }), 0).label).toBe("Finished");
  });
});

describe("cardModel", () => {
  it("collects value, change, Bitcoin, holdings and chart", () => {
    const s = status({
      equity: 1100,
      pnl: 100,
      pnlPct: 10,
      btcReturnPct: 4,
      held: ["crypto:BTC/USD"],
      history: [
        [0, 1000],
        [10, 1100],
      ],
    });
    const pos: PositionView[] = [
      { marketId: "crypto:BTC/USD", venue: "crypto", symbol: "BTC/USD", qty: 0.01, avgPrice: 60000, lastPrice: 66000, unrealized: 60, mode: "paper", live: false },
    ];
    const m = cardModel(s, pos, 20);
    expect(m.value).toBe(1100);
    expect(m.tone).toBe("up");
    expect(m.vsBtcPts).toBeCloseTo(6);
    expect(m.holdings.map((h) => h.coin)).toEqual(["BTC"]);
    expect(m.chart).toEqual([1000, 1100]);
    expect(m.status.line).toBe("Running. Holds 1 asset.");
  });
  it("has no Bitcoin comparison when none is known", () => {
    expect(cardModel(status(), [], 20).vsBtcPts).toBeNull();
  });
});

describe("words", () => {
  it("tone ignores sub-cent noise", () => {
    expect(toneOf(0.001)).toBe("flat");
    expect(toneOf(-1)).toBe("down");
    expect(toneOf(null)).toBe("flat");
  });
  it("vs Bitcoin in one line", () => {
    expect(vsBtcText(1.234)).toBe("Ahead of Bitcoin by 1.2 pts");
    expect(vsBtcText(-3)).toBe("Behind Bitcoin by 3.0 pts");
    expect(vsBtcText(0.01)).toBe("Level with Bitcoin");
    expect(vsBtcText(null)).toBe("No Bitcoin comparison yet");
  });
  it("totals cover active autopilots only", () => {
    const t = totals([
      status({ equity: 1100, startCapital: 1000 }),
      status({ state: "stopped", equity: 500, startCapital: 1000 }),
    ]);
    expect(t).toMatchObject({ value: 1100, amount: 1000, pnl: 100, count: 1 });
    expect(t.pnlPct).toBeCloseTo(10);
  });
});

describe("guided start", () => {
  it("parses typed amounts", () => {
    expect(parseAmount("$1,250")).toBe(1250);
    expect(parseAmount("abc")).toBeNaN();
    expect(parseAmount("")).toBeNaN();
  });
  it("checks the amount", () => {
    expect(amountProblem("1000")).toBeNull();
    expect(amountProblem("5")).toBe("At least $10.");
    expect(amountProblem("x")).toBe("Enter an amount in dollars.");
    expect(amountProblem("2000000")).toBe("At most $1,000,000.");
  });
  it("more careful means a higher floor", () => {
    const low = floorFor(1000, "low")!;
    const med = floorFor(1000, "medium")!;
    const high = floorFor(1000, "high")!;
    expect(low).toBeCloseTo(700);
    expect(med).toBeCloseTo(850);
    expect(high).toBeCloseTo(930);
    expect(low < med && med < high).toBe(true);
  });
  it("recognises its own care levels and nothing else", () => {
    expect(careOf(CARE.medium.stop)).toBe("medium");
    expect(careOf({ maxLossPct: 12, onTakeProfit: "stop" })).toBeNull();
    expect(careOf({ ...CARE.high.stop, maxLossUsd: 50 })).toBeNull();
  });
  it("starts a practice autopilot with auto pick and the chosen stop rules", () => {
    const c = startConfig({ amount: "2,000", care: "high", account: "demo", assetClass: "crypto" }, "bybit", 1_700_000_000_000);
    expect(c.mode).toBe("demo");
    expect(c.venue).toBe("bybit");
    expect(c.capitalUsd).toBe(2000);
    expect(c.sleeves).toEqual([]);
    expect(c.stop).toEqual({ maxLossPct: 7, trailingPct: 10, onTakeProfit: "stop" });
    expect(c.flattenOnStop).toBe(true);
    expect(c.confirm).toBeUndefined();
    // the stop rules are a copy, not the shared constant
    c.stop.maxLossPct = 1;
    expect(CARE.high.stop.maxLossPct).toBe(7);
  });
});

describe("activity", () => {
  it("parses fills the way the engine writes them", () => {
    expect(parseFill("Paper FILL Buy 0.0123 crypto:BTC/USD @ 67250.0000")).toEqual({
      side: "buy",
      qty: 0.0123,
      marketId: "crypto:BTC/USD",
      price: 67250,
      mode: "Paper",
    });
    expect(parseFill("DEMO FILL Sell -0.500000 alpaca:ETH/USD @ 3000.0000 (fee in coin)")?.side).toBe("sell");
    expect(parseFill("Rebalanced toward x")).toBeNull();
  });
  it("keeps the same lines as the engine's events ring", () => {
    expect(isEvent({ kind: "fill", message: "x" })).toBe(true);
    expect(isEvent({ kind: "signal", message: "Rebalanced toward the lab" })).toBe(true);
    expect(isEvent({ kind: "signal", message: "EMA cross on BTC" })).toBe(false);
    expect(isEvent({ kind: "system", message: "Autopilot \"A\" paused" })).toBe(true);
    expect(isEvent({ kind: "system", message: "Forecasts settled" })).toBe(false);
  });
  it("turns a fill into a plain row", () => {
    const it = fromJournal(entry({ kind: "fill", message: "Paper FILL Buy 0.5 crypto:ETH/USD @ 3000.0000" }));
    expect(it).toMatchObject({ kind: "buy", title: "Bought ETH", amount: "$1,500.00", real: false });
  });
  it("marks real money fills", () => {
    const it = fromJournal(entry({ kind: "fill", message: "LIVE FILL Sell 1 crypto:SOL/USD @ 150.0000", mode: "live" }));
    expect(it).toMatchObject({ kind: "sell", title: "Sold SOL", real: true });
  });
  it("skips placed orders, the fill is the row", () => {
    expect(fromJournal(entry({ kind: "order", message: "Paper order Buy" }))).toBeNull();
  });
  it("shortens a long message to its first sentence", () => {
    expect(shortLine("First part. Second part.")).toBe("First part");
    expect(shortLine("x".repeat(200), 20).length).toBe(20);
  });
  it("labels days", () => {
    const now = new Date(2026, 9, 15, 12).getTime();
    expect(dayLabel(new Date(2026, 9, 15, 1).getTime(), now)).toBe("Today");
    expect(dayLabel(new Date(2026, 9, 14, 23).getTime(), now)).toBe("Yesterday");
    expect(dayLabel(new Date(2026, 9, 13, 9).getTime(), now)).toMatch(/13 Oct/);
    expect(dayLabel(new Date(2025, 9, 13, 9).getTime(), now)).toMatch(/2025/);
  });
  it("groups by day, newest first, merges events and journal and adds alerts", () => {
    const now = new Date(2026, 9, 15, 12).getTime();
    const t1 = new Date(2026, 9, 15, 10).getTime();
    const t2 = new Date(2026, 9, 14, 9).getTime();
    const fill = entry({ id: "j1", ts: t1, kind: "fill", message: "Paper FILL Buy 1 crypto:BTC/USD @ 100.0" });
    const reb = entry({ id: "j2", ts: t2, kind: "signal", message: "Rebalanced toward the lab's weights of 2026-10-14: 3 orders" });
    const days = timeline(
      {
        events: [fill, reb],
        journal: [fill],
        alerts: [{ ts: t1 + 1, kinds: ["floorHit"], text: "**Floor hit** A stopped", delivered: true, error: null }],
        digest: { ts: t2 + 1, text: "Daily report. Up 1%." },
      },
      now,
    );
    expect(days.map((d) => d.label)).toEqual(["Today", "Yesterday"]);
    expect(days[0].items.map((i) => i.kind)).toEqual(["alert", "buy"]);
    expect(days[0].summary).toBe("1 trade · 1 alert");
    expect(days[1].items.map((i) => i.kind)).toEqual(["summary", "rebalance"]);
    expect(days[1].summary).toBe("1 rebalance");
    const trades = timeline({ events: [fill, reb], alerts: [{ ts: t1, kinds: ["test"], text: "t", delivered: true, error: null }] }, now, "trades");
    expect(trades.flatMap((d) => d.items.map((i) => i.kind))).toEqual(["buy", "rebalance"]);
  });
  it("counts in words", () => {
    expect(daySummary([])).toBe("");
  });
});

describe("alerts", () => {
  it("titles an alert by its kinds", () => {
    expect(alertTitle({ kinds: ["floorHit"] })).toBe("Loss limit reached");
    expect(alertTitle({ kinds: ["killSwitch", "orderRejects"] })).toBe("Kill switch +1");
    expect(alertTitle({ kinds: [] })).toBe("Alert");
    expect(alertTitle({ kinds: ["trade", "trade"], title: "Rebalance · Momentum" })).toBe("Rebalance · Momentum +1");
    expect(alertTitle({ kinds: ["event"], title: "Factory 2026-10-17" })).toBe("Factory 2026-10-17");
  });
  it("shows a Telegram post without its markup", () => {
    expect(plainText("<b>🚨 Kill &amp; switch</b>\n<pre>P&amp;L  -$5 &lt;x&gt;</pre>\n<i>Pythia</i>")).toBe("🚨 Kill & switch\nP&L  -$5 <x>\nPythia");
    expect(plainText("**🛑 Floor hit**\n```\nEquity  $9\n```")).toBe("🛑 Floor hit\n\nEquity  $9\n");
  });
  it("checks and words quiet hours", () => {
    expect(validHhmm("23:00") && validHhmm("7:05")).toBe(true);
    expect(validHhmm("24:00") || validHhmm("9pm") || validHhmm("12:60")).toBe(false);
    expect(quietLine({ enabled: true, start: "23:00", end: "07:00", timezone: "Europe/Berlin" })).toBe("23:00 to 07:00");
    expect(quietLine({ enabled: false, start: "23:00", end: "07:00", timezone: "Europe/Berlin" })).toBe("Off");
  });
  it("words the message language and says when the server fixes it", () => {
    expect(languageOf({})).toEqual({ lang: "en", note: null });
    expect(languageOf({ language: "de", languageEnv: null })).toEqual({ lang: "de", note: null });
    const forced = languageOf({ language: "en", languageEnv: "de" });
    expect(forced.lang).toBe("de");
    expect(forced.note).toContain("PYTHIA_ALERT_LANG");
    expect(forced.note).toContain("Deutsch");
    expect(ALERT_LANGUAGES.map((l) => l.label)).toEqual(["English", "Deutsch"]);
  });
  it("groups the switches by who sends them", () => {
    const c = (id: string, source: "engine" | "lab") => ({ id, label: id, emoji: "", about: "", source, on: true }) as never;
    const g = groupCategories([c("trades", "engine"), c("weekly", "lab"), c("risk", "engine")]);
    expect(g.engine.map((x: { id: string }) => x.id)).toEqual(["trades", "risk"]);
    expect(g.lab.map((x: { id: string }) => x.id)).toEqual(["weekly"]);
  });
  it("says how it went", () => {
    expect(deliveryOf({ delivered: true, error: null }).label).toBe("Delivered");
    expect(deliveryOf({ delivered: false, error: null, reason: "muted" }).label).toBe("Muted");
    expect(deliveryOf({ delivered: false, error: null, reason: "hourlyLimit" }).tone).toBe("warn");
    expect(deliveryOf({ delivered: false, error: null, reason: "quiet" }).label).toBe("Quiet hours");
    expect(deliveryOf({ delivered: false, error: "HTTP 500" }).label).toBe("Failed: HTTP 500");
  });
  it("says how long it is muted", () => {
    expect(muteText(0, 1000)).toBeNull();
    expect(muteText(1000 + 45 * 60_000, 1000)).toBe("Muted for 45 min");
    expect(muteText(1000 + 3 * 3_600_000, 1000)).toBe("Muted for 3 h");
    expect(muteText(1000 + 3 * 86_400_000, 1000)).toMatch(/^Muted until /);
  });
  it("names the destination and the counts", () => {
    expect(destinationName("telegram")).toBe("Telegram");
    expect(destinationName(null)).toBe("nowhere");
    expect(countsLine({ sentToday: 4, failedToday: 1, suppressedToday: 0 })).toBe("4 sent today · 1 failed");
  });
});
