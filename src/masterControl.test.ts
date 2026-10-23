import { describe, expect, it } from "vitest";
import {
  FIXED_MAX_SHARE,
  SHARE_BUTTONS,
  confirmQuestion,
  hasOverride,
  hhmm,
  isPaused,
  limitsKind,
  limitsText,
  lowText,
  maxShare,
  needsConfirm,
  parseShare,
  patchOf,
  pausedText,
  shareRefusal,
  shareSourceText,
  shareText,
} from "./masterControl";
import type { ControlFile, StatusControl } from "./pumpfunLive";

/** 14:05 local time on a day in October 2026. */
const AT = new Date(2026, 9, 23, 14, 5, 30).getTime();

function control(over: Partial<StatusControl> = {}): StatusControl {
  return {
    limits: "wallet", share: 0.1, shareSource: "ack", shareSince: null, ackShare: 0.1, requestedShare: null,
    paused: false, pausedSince: null, note: null, controlOk: true, ...over,
  };
}

const file = (over: Partial<ControlFile> = {}): ControlFile => ({ share: null, paused: false, setAt: null, shareSetAt: null, pausedAt: null, ...over });

describe("the share", () => {
  it("has the six buttons from 5 % to 100 %", () => {
    expect(SHARE_BUTTONS).toEqual([0.05, 0.1, 0.25, 0.5, 0.75, 1]);
    expect(SHARE_BUTTONS.map(shareText)).toEqual(["5 %", "10 %", "25 %", "50 %", "75 %", "100 %"]);
    expect(shareText(0.125)).toBe("12.5 %");
    expect(shareText(null)).toBe("n/a");
  });

  it("reads a custom percent, valid only from 1 % to 100 %", () => {
    expect(parseShare("12")).toEqual({ share: 0.12, error: null });
    expect(parseShare("12.5")).toEqual({ share: 0.125, error: null });
    expect(parseShare(" 12 % ")).toEqual({ share: 0.12, error: null });
    expect(parseShare("12,5%")).toEqual({ share: 0.125, error: null });
    expect(parseShare("1")).toEqual({ share: 0.01, error: null });
    expect(parseShare("100")).toEqual({ share: 1, error: null });
    expect(parseShare("")).toEqual({ share: null, error: null });
    for (const bad of ["0.5", "0", "101", "-5", "abc", "1e2", "12 %%", "Infinity"]) {
      expect(parseShare(bad).share, bad).toBeNull();
      expect(parseShare(bad).error, bad).toBe("A percent from 1 to 100.");
    }
  });

  it("turns each action into the patch the engine takes", () => {
    expect(patchOf({ kind: "share", share: 0.25 })).toEqual({ share: 0.25 });
    expect(patchOf({ kind: "reset" })).toEqual({ resetShare: true });
    expect(patchOf({ kind: "stop" })).toEqual({ paused: true });
    expect(patchOf({ kind: "start" })).toEqual({ paused: false });
  });
});

describe("needsConfirm", () => {
  it("asks for Start and for raising the share above 50 %, nothing else", () => {
    expect(needsConfirm({ kind: "start" }, 0.1)).toBe(true);
    expect(needsConfirm({ kind: "stop" }, 0.1)).toBe(false);
    expect(needsConfirm({ kind: "reset" }, 0.1)).toBe(false);
    expect(needsConfirm({ kind: "share", share: 0.75 }, 0.1)).toBe(true);
    expect(needsConfirm({ kind: "share", share: 1 }, 0.75)).toBe(true);
    expect(needsConfirm({ kind: "share", share: 0.75 }, null)).toBe(true);
    // 50 % itself, lowering, or the same share ask nothing.
    expect(needsConfirm({ kind: "share", share: 0.5 }, 0.1)).toBe(false);
    expect(needsConfirm({ kind: "share", share: 0.75 }, 1)).toBe(false);
    expect(needsConfirm({ kind: "share", share: 0.75 }, 0.75)).toBe(false);
    expect(needsConfirm({ kind: "share", share: 0.25 }, 0.1)).toBe(false);
  });

  it("says what is at stake", () => {
    expect(confirmQuestion({ kind: "share", share: 0.75 }, "pumpfun")).toContain("75 % of the wallet");
    expect(confirmQuestion({ kind: "start" }, "pumpfun")).toContain("buys again");
    expect(confirmQuestion({ kind: "start" }, "onchain")).toContain("books trade again");
  });
});

describe("where the share comes from and the Stop", () => {
  it("names the source, with the local time of the owner's override", () => {
    expect(hhmm(AT)).toBe("14:05");
    expect(shareSourceText(control({ shareSource: "default" }))).toBe("code default");
    expect(shareSourceText(control({ shareSource: "ack" }))).toBe("confirmation file");
    expect(shareSourceText(control({ shareSource: "owner", shareSince: AT }))).toBe("your override since 14:05");
    // While the bot is down: the control file.
    expect(shareSourceText(null, file({ share: 0.5, shareSetAt: AT }))).toBe("your override since 14:05");
    expect(shareSourceText(null, file())).toBe("confirmation file");
  });

  it("says paused by you since hh:mm, from the control file first", () => {
    expect(pausedText(control({ paused: true, pausedSince: AT }))).toBe("paused by you since 14:05");
    expect(pausedText(null, file({ paused: true, pausedAt: AT }))).toBe("paused by you since 14:05");
    expect(pausedText(control({ paused: true }), null)).toBe("paused by you");
    expect(pausedText(control())).toBeNull();
    // Start was pressed: the file says go even while the status still says paused.
    expect(isPaused(control({ paused: true }), file())).toBe(false);
    expect(isPaused(control(), file({ paused: true }))).toBe(true);
  });

  it("knows when an override is set", () => {
    expect(hasOverride(control({ shareSource: "owner" }))).toBe(true);
    expect(hasOverride(control())).toBe(false);
    expect(hasOverride(control({ shareSource: "owner" }), file())).toBe(false);
    expect(hasOverride(null, file({ share: 0.25 }))).toBe(true);
  });

  it("says when the wallet is too small for one trade", () => {
    expect(lowText({ have: 0.2, need: 0.25, unit: "SOL" })).toBe("The wallet is below what one trade needs: have 0.2 SOL, need 0.25 SOL.");
    expect(lowText({ have: 4, need: 5.5, unit: "USD" })).toBe("The wallet is below what one trade needs: have 4.00 USD, need 5.50 USD.");
    expect(lowText(null)).toBeNull();
    expect(lowText({ have: null, need: 1, unit: "SOL" })).toBeNull();
  });
});

describe("limits: wallet or fixed", () => {
  it("takes the first kind it finds, fixed when none", () => {
    expect(limitsKind(null, "wallet", "fixed")).toBe("wallet");
    expect(limitsKind(undefined, null)).toBe("fixed");
    expect(limitsText("wallet")).toBe("limits: wallet");
    expect(limitsText("fixed")).toBe("limits: fixed");
  });

  it("lets pump.fun raise only with limits=wallet; without it at most the file's share, 10 % at most", () => {
    expect(FIXED_MAX_SHARE).toBe(0.1);
    expect(maxShare("pumpfun", "wallet", 0.1)).toBe(1);
    expect(maxShare("pumpfun", "fixed", null)).toBe(0.1);
    expect(maxShare("pumpfun", "fixed", 0.05)).toBe(0.05);
    expect(maxShare("pumpfun", "fixed", 0.5)).toBe(0.1);
    expect(maxShare("onchain", "fixed", null)).toBe(1);
    expect(shareRefusal(0.1, "pumpfun", "fixed", null)).toBeNull();
    expect(shareRefusal(0.25, "pumpfun", "fixed", null)).toBe("Without limits=wallet in the confirmation file the share can only be lowered, at most 10 %.");
    expect(shareRefusal(1, "pumpfun", "wallet", 0.1)).toBeNull();
    expect(shareRefusal(1, "onchain", "fixed", null)).toBeNull();
  });
});
