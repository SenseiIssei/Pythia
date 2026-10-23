import { afterEach, describe, expect, it, vi } from "vitest";
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Button } from "../design";
import { ConfirmAction } from "../pagekit";
import { MasterView, PumpfunMaster, OnchainMaster, WALLET_LIMIT, type MasterViewProps } from "./MasterPanel";
import { pumpfunControl, type ControlPatch, type PumpfunView, type StatusControl } from "../pumpfunLive";
import { onchainControl, parseOnchainView } from "../onchainLive";

type El = ReactElement<{ children?: ReactNode; onClick?: () => void; onConfirm?: () => void; disabled?: boolean; question?: ReactNode }>;

/** Every element under `node`, following children only (the view has no state, so it reads as a tree). */
function elements(node: ReactNode, out: El[] = []): El[] {
  if (Array.isArray(node)) for (const n of node) elements(n, out);
  else if (isValidElement(node)) {
    out.push(node as El);
    elements((node as El).props.children, out);
  }
  return out;
}

const text = (n: ReactNode): string => (typeof n === "string" || typeof n === "number" ? String(n) : Array.isArray(n) ? n.map(text).join("") : isValidElement(n) ? text((n as El).props.children) : "");

/** The button or confirm labelled `label`, and whether it asks first. */
function control(tree: ReactNode, label: string): { el: El; asks: boolean } {
  const el = elements(tree).find((e) => (e.type === Button || e.type === ConfirmAction) && text(e.props.children) === label);
  if (!el) throw new Error(`no ${label} button`);
  return { el, asks: el.type === ConfirmAction };
}

/** Click it; a confirm acts only on its second step (the sheet's confirm). */
function click(tree: ReactNode, label: string) {
  const { el, asks } = control(tree, label);
  if (asks) el.props.onConfirm?.();
  else el.props.onClick?.();
}

const status = (over: Partial<StatusControl> = {}): StatusControl => ({
  limits: "wallet", share: 0.1, shareSource: "ack", shareSince: null, ackShare: 0.1, requestedShare: null,
  paused: false, pausedSince: null, note: null, controlOk: true, ...over,
});

function view(over: Partial<MasterViewProps> = {}) {
  const sent: ControlPatch[] = [];
  const props: MasterViewProps = {
    bot: "pumpfun", control: status(), file: null, kind: "wallet", ackShare: 0.1, low: null, can: true,
    custom: "", onCustom: () => {}, busy: false, msg: null, err: null, send: (p) => sent.push(p), ...over,
  };
  return { tree: MasterView(props), sent };
}

describe("the Master panel", () => {
  it("posts the share, Stop and the reset at once, without asking", () => {
    const { tree, sent } = view({ control: status({ shareSource: "owner", share: 0.25 }) });
    for (const l of ["5 %", "10 %", "25 %", "50 %", "Stop", "Back to the confirmation file"]) expect(control(tree, l).asks, l).toBe(false);
    click(tree, "25 %");
    click(tree, "Stop");
    click(tree, "Back to the confirmation file");
    expect(sent).toEqual([{ share: 0.25 }, { paused: true }, { resetShare: true }]);
  });

  it("asks before Start and before raising above 50 %", () => {
    const { tree, sent } = view({ control: status({ paused: true, pausedSince: Date.now() }) });
    expect(control(tree, "Start").asks).toBe(true);
    expect(text(control(tree, "Start").el.props.question)).toContain("buys again");
    expect(control(tree, "75 %").asks).toBe(true);
    expect(control(tree, "100 %").asks).toBe(true);
    expect(elements(tree).some((e) => e.type === Button && text(e.props.children) === "Stop")).toBe(false);
    click(tree, "Start");
    click(tree, "75 %");
    expect(sent).toEqual([{ paused: false }, { share: 0.75 }]);
    // Already at 100 %: going down to 75 % asks nothing.
    expect(control(view({ control: status({ share: 1 }) }).tree, "75 %").asks).toBe(false);
  });

  it("sets a custom share, asking when it raises above 50 %", () => {
    const a = view({ custom: "12.5" });
    expect(control(a.tree, "Set").asks).toBe(false);
    click(a.tree, "Set");
    expect(a.sent).toEqual([{ share: 0.125 }]);
    expect(control(view({ custom: "60 %" }).tree, "Set").asks).toBe(true);
    expect(control(view({ custom: "0.5" }).tree, "Set").el.props.disabled).toBe(true);
    expect(control(view({ custom: "" }).tree, "Set").el.props.disabled).toBe(true);
  });

  it("without limits=wallet pump.fun can only lower: the buttons above 10 % are off, with the reason", () => {
    const { tree } = view({ kind: "fixed", ackShare: null });
    expect(control(tree, "5 %").el.props.disabled).toBe(false);
    expect(control(tree, "10 %").el.props.disabled).toBe(false);
    for (const l of ["25 %", "50 %", "75 %", "100 %"]) expect(control(tree, l).el.props.disabled, l).toBe(true);
    const html = renderToStaticMarkup(tree);
    expect(html).toContain("limits: fixed");
    expect(html).toContain("the share can only be lowered, at most 10 %");
  });

  it("is off with a hint when not on the server, and the kill switch is never offered here", () => {
    const { tree } = view({ can: false, control: status({ shareSource: "owner" }) });
    for (const l of ["5 %", "100 %", "Stop", "Set", "Back to the confirmation file"]) expect(control(tree, l).el.props.disabled, l).toBe(true);
    const html = renderToStaticMarkup(tree);
    expect(html).toContain("connected backend on the server");
    expect(html).not.toMatch(/kill file|remove the kill/i);
  });

  it("pump.fun shows Bremse: an/aus; off asks first, on does not, both post brake", () => {
    const file = (brake: boolean | null) => ({ share: null, paused: false, setAt: null, shareSetAt: null, pausedAt: null, brake });
    const on = view({ file: file(true) });
    expect(renderToStaticMarkup(on.tree)).toContain("Bremse: an");
    expect(control(on.tree, "Bremse aus").asks).toBe(true);
    expect(text(control(on.tree, "Bremse aus").el.props.question)).toContain("drawdown brake");
    click(on.tree, "Bremse aus");
    expect(on.sent).toEqual([{ brake: false }]);
    const off = view({ file: file(false) });
    expect(renderToStaticMarkup(off.tree)).toContain("Bremse: aus");
    expect(control(off.tree, "Bremse an").asks).toBe(false);
    click(off.tree, "Bremse an");
    expect(off.sent).toEqual([{ brake: true }]);
    // Unset reads as on (the engine's default); without limits=wallet it cannot be switched off; on-chain has none.
    expect(renderToStaticMarkup(view({ file: null }).tree)).toContain("Bremse: an");
    expect(control(view({ kind: "fixed", file: file(true) }).tree, "Bremse aus").el.props.disabled).toBe(true);
    expect(renderToStaticMarkup(view({ bot: "onchain" }).tree)).not.toContain("Bremse");
  });

  it("shows the share, its source, the pause, the note and a low wallet", () => {
    const at = new Date(2026, 9, 23, 14, 5).getTime();
    const html = renderToStaticMarkup(
      view({
        control: status({ share: 0.5, shareSource: "owner", shareSince: at, paused: true, pausedSince: at, note: "Lowered to 10 %: limits=wallet is not set." }),
        low: { have: 0.2, need: 0.25, unit: "SOL" },
      }).tree,
    );
    expect(html).toContain("Master");
    expect(html).toContain("limits: wallet");
    expect(html).toContain("50 %");
    expect(html).toContain("your override since 14:05");
    expect(html).toContain("Paused by you since 14:05");
    expect(html).toContain("Lowered to 10 %");
    expect(html).toContain("have 0.2 SOL, need 0.25 SOL");
    expect(html).toContain("kill switch stays the separate emergency stop");
  });
});

describe("the panels on the pages", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("post to the bots' control routes", async () => {
    vi.stubEnv("VITE_PYTHIA_SERVER", "/api/pythia");
    const asked: { url: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", async (u: string, init?: RequestInit) => {
      asked.push({ url: String(u), body: init?.body ? JSON.parse(String(init.body)) : null });
      return new Response(JSON.stringify({ share: 0.25, paused: false, setAt: 1, shareSetAt: 1, pausedAt: null, effective: null }), { status: 200 });
    });
    const pf = view({ send: (p) => void pumpfunControl(p) });
    click(pf.tree, "25 %");
    const oc = view({ bot: "onchain", send: (p) => void onchainControl(p), control: status({ paused: true }) });
    click(oc.tree, "Start");
    await vi.waitFor(() => expect(asked).toHaveLength(2));
    expect(asked).toEqual([
      { url: "/api/pythia/api/pumpfun/live/control", body: { share: 0.25 } },
      { url: "/api/pythia/api/onchain/live/control", body: { paused: false } },
    ]);
    expect(await onchainControl({ resetShare: true })).toEqual({ share: 0.25, paused: false, setAt: 1, shareSetAt: 1, pausedAt: null, effective: null });
  });

  it("pass the engine's refusal on and need the server", async () => {
    vi.stubEnv("VITE_PYTHIA_SERVER", "/api/pythia");
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ error: "without limits=wallet in the confirmation file the share can only be lowered, at most 10 %" }), { status: 400 }));
    await expect(pumpfunControl({ share: 0.5 })).rejects.toThrow("at most 10 %");
    vi.stubEnv("VITE_PYTHIA_SERVER", "");
    await expect(pumpfunControl({ paused: true })).rejects.toThrow("connected backend");
    await expect(onchainControl({ paused: true })).rejects.toThrow("connected backend");
  });

  it("pump.fun with wallet limits: the stake and no daily loss or total budget; off on the desktop", () => {
    vi.stubEnv("VITE_PYTHIA_SERVER", "");
    const v = {
      running: true,
      status: { ack: { limits: "wallet", stakeShare: 0.5 }, limits: { kind: "wallet" }, stake: { sol: 0.45, why: "50 % of 0.90 SOL (limits: wallet)", share: 0.5 }, control: status({ share: 0.5 }), low: null },
      control: { share: null, paused: false, setAt: null, shareSetAt: null, pausedAt: null },
    } as unknown as PumpfunView;
    const html = renderToStaticMarkup(<PumpfunMaster v={v} onDone={() => {}} />);
    expect(html).toContain("limits: wallet");
    expect(html).toContain("0.450 SOL");
    expect(html).toContain("50 % of 0.90 SOL (limits: wallet)");
    expect(html).toContain(WALLET_LIMIT);
    expect(html).toContain("connected backend on the server");
    // An old status file without any of the new fields still shows.
    expect(renderToStaticMarkup(<PumpfunMaster v={{ running: false, status: null } as unknown as PumpfunView} onDone={() => {}} />)).toContain("limits: fixed");
  });

  it("on-chain: the share, the caps and the book size from the status", () => {
    vi.stubEnv("VITE_PYTHIA_SERVER", "/api/pythia");
    const v = parseOnchainView({
      running: true,
      status: {
        t: 1, running: true, on: true, ack: { mode: "test", limits: "wallet" },
        limits: { kind: "wallet", maxTotalUsd: 200, maxTradeUsd: 50, maxDailyLossUsd: null, maxConvertUsd: 200 },
        control: { limits: "wallet", share: null, shareSource: "ack", bookUsd: 150, ackBookUsd: 150, paused: true, pausedSince: 1, controlOk: true },
        low: { have: 0.01, need: 0.03, unit: "SOL" },
      },
      control: { share: null, paused: true, setAt: 1, shareSetAt: null, pausedAt: 1 },
    });
    expect(v.status?.control?.bookUsd).toBe(150);
    expect(v.status?.limits?.kind).toBe("wallet");
    expect(v.control?.paused).toBe(true);
    const html = renderToStaticMarkup(<OnchainMaster v={v} onDone={() => {}} />);
    expect(html).toContain("$150.00 a book");
    expect(html).toContain("$50.00");
    expect(html).toContain(WALLET_LIMIT);
    expect(html).toContain("Start");
    expect(html).toContain("your conversions still work");
    expect(html).toContain("have 0.01 SOL, need 0.03 SOL");
  });
});
