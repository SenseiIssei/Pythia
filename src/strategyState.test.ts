import { describe, expect, it } from "vitest";
import { changeStrategyState } from "./strategyState";

const CLAIMED =
  'EMA Cross runs in the autopilot "Weekend", which sets its state. Pause the autopilot to hold it, or stop it to change the strategy.';

describe("changeStrategyState", () => {
  it("returns nothing when the engine accepts", async () => {
    const seen: string[] = [];
    const msg = await changeStrategyState(async (id, s) => void seen.push(`${id}:${s}`), "ema", "paused");
    expect(msg).toBe("");
    expect(seen).toEqual(["ema:paused"]);
  });

  it("returns the server's refusal sentence instead of dropping it", async () => {
    const msg = await changeStrategyState(() => Promise.reject(new Error(CLAIMED)), "ema", "paused");
    expect(msg).toBe(CLAIMED);
  });

  it("returns Tauri's refusal, which arrives as a plain string", async () => {
    const msg = await changeStrategyState(() => Promise.reject(CLAIMED), "ema", "paper");
    expect(msg).toBe(CLAIMED);
  });
});
