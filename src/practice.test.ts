import { describe, expect, it } from "vitest";
import { DAY_MS } from "./autopilot";
import type { ForwardReport, ForwardRow } from "./lab";
import {
  PLUS_MINUS,
  benchmark,
  benchmarkLine,
  cashReason,
  coinOf,
  contrastRatio,
  direction,
  fillRows,
  fmtPrice,
  fmtQty,
  forwardSummary,
  holdings,
  nextLabSignalMs,
  practiceAutopilots,
  routeBadge,
  signedPctText,
  signedUsd,
  tradesToday,
  usesLabSignal,
} from "./practice";
import type { AutopilotStatus, Market, Order, PositionView } from "./types";

const T0 = Date.UTC(2026, 9, 12, 10, 0); // 12 Oct 2026, 10:00 UTC

function ap(over: Partial<AutopilotStatus> = {}): AutopilotStatus {
  return {
    config: {
      id: "a",
      name: "Demo A",
      mode: "demo",
      venue: "alpaca",
      assetClass: "crypto",
      capitalUsd: 1_000,
      sleeves: [{ strategyId: "lab:tsmom_top20", weight: 1 }],
      stop: { onTakeProfit: "stop" },
      flattenOnStop: true,
    },
    state: "running",
    stopReason: null,
    pausedReason: null,
    startedMs: T0 - 2 * DAY_MS,
    stoppedMs: null,
    startCapital: 1_000,
    equity: 1_030,
    pnl: 30,
    pnlPct: 3,
    peakEquity: 1_040,
    drawdownPct: 1,
    floorEquity: null,
    targetEquity: null,
    trades: 4,
    fees: 1.2,
    openPositions: 1,
    bySleeve: [
      { strategyId: "lab:tsmom_top20", name: "Momentum", weight: 1, pnl: 30, trades: 4, why: "", markets: ["alpaca:BTC/USD", "alpaca:ETH/USD"] },
    ],
    lastAction: null,
    history: [
      [T0 - 2 * DAY_MS, 1_000],
      [T0, 1_030],
    ],
    ...over,
  };
}

function order(over: Partial<Order> = {}): Order {
  return {
    id: "o1",
    ts: T0 - 60_000,
    strategyId: "lab:tsmom_top20",
    marketId: "alpaca:ETH/USD",
    venue: "alpaca",
    side: "buy",
    type: "market",
    qty: 0.1,
    status: "filled",
    filledQty: 0.1,
    avgFillPrice: 2_500,
    mode: "paper",
    route: "demo",
    ...over,
  };
}

function pos(over: Partial<PositionView> = {}): PositionView {
  return {
    marketId: "alpaca:ETH/USD",
    venue: "alpaca",
    symbol: "ETH/USD",
    qty: 0.1,
    avgPrice: 2_500,
    lastPrice: 2_600,
    unrealized: 10,
    mode: "paper",
    live: false,
    demo: true,
    ...over,
  };
}

describe("formatting", () => {
  it("signs dollars with a plus or a real minus and never signs zero", () => {
    expect(signedUsd(12.345)).toBe("+$12.35");
    expect(signedUsd(-1234.5)).toBe("−$1,234.50");
    expect(signedUsd(0)).toBe("$0.00");
    expect(signedUsd(-0.001)).toBe("$0.00");
    expect(signedUsd(NaN)).toBe("n/a");
  });

  it("signs percentages the same way", () => {
    expect(signedPctText(3)).toBe("+3.00%");
    expect(signedPctText(-0.4, 1)).toBe("−0.4%");
    expect(signedPctText(0.0001)).toBe("0.00%");
    expect(signedPctText(null)).toBe("n/a");
  });

  it("calls tiny moves flat", () => {
    expect(direction(1)).toBe("up");
    expect(direction(-1)).toBe("down");
    expect(direction(0.001)).toBe("flat");
    expect(direction(undefined)).toBe("flat");
  });

  it("formats coins, prices and amounts for a phone", () => {
    expect(coinOf("BTC/USD")).toBe("BTC");
    expect(coinOf("AAPL")).toBe("AAPL");
    expect(fmtPrice(67_250)).toBe("$67,250.00");
    expect(fmtPrice(3.45123)).toBe("$3.4512");
    expect(fmtPrice(0.000123)).toBe("$0.000123");
    expect(fmtQty(0.0123456)).toBe("0.012346");
    expect(fmtQty(1.5)).toBe("1.5");
    expect(fmtQty(1234.567)).toBe("1,234.57");
  });

  it("keeps plus and minus readable on every surface the app draws", () => {
    for (const surface of ["#13131a", "#1a1a24", "#0a0a0f"]) {
      for (const c of Object.values(PLUS_MINUS)) {
        expect(contrastRatio(c, surface)).toBeGreaterThanOrEqual(4.5);
      }
    }
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 5);
  });
});

describe("practiceAutopilots", () => {
  it("shows active ones first, then the ones stopped in the last week", () => {
    const run = ap({ config: { ...ap().config, id: "run" } });
    const recent = ap({ config: { ...ap().config, id: "recent" }, state: "stopped", stoppedMs: T0 - DAY_MS });
    const old = ap({ config: { ...ap().config, id: "old" }, state: "finished", stoppedMs: T0 - 9 * DAY_MS });
    expect(practiceAutopilots([old, recent, run], T0).map((s) => s.config.id)).toEqual(["run", "recent"]);
  });
});

describe("nextLabSignalMs", () => {
  it("is today at 04:15 UTC before then and tomorrow after", () => {
    expect(nextLabSignalMs(Date.UTC(2026, 9, 12, 3, 0))).toBe(Date.UTC(2026, 9, 12, 4, 15));
    expect(nextLabSignalMs(Date.UTC(2026, 9, 12, 4, 15))).toBe(Date.UTC(2026, 9, 13, 4, 15));
    expect(nextLabSignalMs(Date.UTC(2026, 11, 31, 23, 0))).toBe(Date.UTC(2027, 0, 1, 4, 15));
  });

  it("knows which autopilots run on the lab signal", () => {
    expect(usesLabSignal(ap())).toBe(true);
    const plain = ap({ bySleeve: [], config: { ...ap().config, sleeves: [{ strategyId: "ema-cross-1", weight: 1 }] } });
    expect(usesLabSignal(plain)).toBe(false);
  });
});

describe("holdings", () => {
  it("lists what the engine says it holds, with P&L against cost", () => {
    const h = holdings(ap({ held: ["alpaca:ETH/USD"] }), [pos(), pos({ marketId: "crypto:SOL/USD", symbol: "SOL/USD" })]);
    expect(h).toHaveLength(1);
    expect(h[0].coin).toBe("ETH");
    expect(h[0].value).toBeCloseTo(260);
    expect(h[0].pnl).toBe(10);
    expect(h[0].pnlPct).toBeCloseTo(4);
  });

  it("falls back to its sleeves' markets on an engine without `held`", () => {
    expect(holdings(ap(), [pos()]).map((h) => h.coin)).toEqual(["ETH"]);
    expect(holdings(ap({ state: "stopped", stoppedMs: T0 }), [pos()])).toEqual([]);
  });

  it("explains being in cash", () => {
    expect(cashReason(ap())).toContain("waiting for a signal");
    expect(cashReason(ap({ state: "paused", pausedReason: "live routing is off" }))).toBe("Paused: live routing is off.");
    expect(cashReason(ap({ state: "stopped", stopReason: "stopped by you" }))).toBe("Stopped: stopped by you.");
  });
});

describe("benchmark", () => {
  it("uses the engine's own Bitcoin figure when there is one", () => {
    const b = benchmark(ap({ btcReturnPct: 1.5 }), T0)!;
    expect(b).toEqual({ btcPct: 1.5, runPct: 3, edgePct: 1.5, approximate: false });
    expect(benchmarkLine(b)).toBe("Holding Bitcoin would have made +1.50%; this is ahead by 1.50 points.");
  });

  it("falls back to the price history and says when it is behind", () => {
    const times = [T0 - 2 * DAY_MS, T0 - DAY_MS, T0];
    const closes = [100_000, 103_000, 110_000];
    const b = benchmark(ap(), T0, times, closes)!;
    expect(b.btcPct).toBeCloseTo(10);
    expect(b.runPct).toBeCloseTo(3);
    expect(benchmarkLine(b)).toContain("behind by 7.00 points");
  });

  it("is null with nothing to compare", () => {
    expect(benchmark(ap(), T0)).toBeNull();
  });
});

describe("fills", () => {
  const markets: Market[] = [
    { id: "alpaca:ETH/USD", venue: "alpaca", symbol: "ETH/USD", kind: "crypto", price: 2_600, change24h: 0, updatedAt: T0 },
  ];

  it("counts today's fills of this autopilot only", () => {
    const orders = [
      order(),
      order({ id: "o2", ts: Date.UTC(2026, 9, 11, 23, 0) }),
      order({ id: "o3", strategyId: "other" }),
      order({ id: "o4", status: "rejected", filledQty: 0 }),
    ];
    expect(tradesToday(ap(), orders, T0)).toBe(1);
  });

  it("turns orders into plain rows, newest first, with the fee when known", () => {
    const rows = fillRows(
      [order({ id: "old", ts: T0 - 3_600_000, fee: 0.62 }), order({ id: "new" }), order({ id: "x", strategyId: "other" })],
      markets,
      [ap()],
    );
    expect(rows.map((r) => r.id)).toEqual(["new", "old"]);
    expect(rows[0]).toMatchObject({ coin: "ETH", side: "buy", qty: 0.1, price: 2_500, fee: null, feeNote: "posted end of day", liquidity: "taker", autopilot: "Demo A" });
    expect(rows[0].badge.label).toBe("demo, Alpaca paper");
    expect(rows[1]).toMatchObject({ fee: 0.62, feeNote: null });
  });

  it("says where every fill happened", () => {
    expect(routeBadge("live", "crypto")).toEqual({ label: "real money", tone: "red" });
    expect(routeBadge("demo", "crypto").label).toBe("demo");
    expect(routeBadge(undefined, "crypto").label).toBe("paper, simulated");
  });
});

describe("forwardSummary", () => {
  const row = (name: string, status: string, kind = "book"): ForwardRow => ({ kind, name, status } as ForwardRow);

  it("counts by status and puts autopilots first", () => {
    const r = {
      generated: "",
      generatedMs: T0,
      verdict: "All fine.",
      books: [row("b1", "on_track"), row("b2", "watch"), row("b3", "early")],
      autopilots: [row("a1", "ahead", "autopilot")],
      engine: null,
    } satisfies ForwardReport;
    const s = forwardSummary(r)!;
    expect(s).toMatchObject({ total: 4, onTrack: 1, ahead: 1, watch: 1, early: 1, verdict: "All fine." });
    expect(s.rows.map((x) => x.name)).toEqual(["a1", "b1", "b2", "b3"]);
    expect(forwardSummary(null)).toBeNull();
  });
});
