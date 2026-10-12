// How the Alpaca paper account compares with the demo book, in words for the
// Live page. The numbers come from the engine (`LiveStatus.demoReconcile`).

import type { DemoReconcile, PairCheck, PairStatus } from "./types";

/** One word per status, and whether it needs a person to look. */
export const PAIR_STATUS: Record<PairStatus, { label: string; attention: boolean }> = {
  ok: { label: "matches", attention: false },
  pending: { label: "order in flight", attention: false },
  feeTaken: { label: "fee booked", attention: false },
  corrected: { label: "corrected to Alpaca", attention: false },
  adopted: { label: "adopted", attention: false },
  strayOrder: { label: "unknown open order", attention: true },
  mismatch: { label: "differs", attention: true },
  untracked: { label: "not Pythia's", attention: true },
};

/** Pairs to show: everything that is not a plain match, worst first. */
export function pairsToShow(d: DemoReconcile): PairCheck[] {
  const rank = (p: PairCheck) => (PAIR_STATUS[p.status].attention ? 0 : 1);
  return d.pairs
    .filter((p) => p.status !== "ok")
    .slice()
    .sort((a, b) => rank(a) - rank(b) || Math.abs(b.diffUsd) - Math.abs(a.diffUsd));
}

/** A one-line headline: when it ran and whether the two agree. */
export function reconcileHeadline(d: DemoReconcile, now: number): string {
  if (d.checkedAt === 0) {
    return d.error ? `Alpaca paper not read yet: ${d.error}` : "Alpaca paper not reconciled yet";
  }
  const mins = Math.max(0, Math.round((now - d.checkedAt) / 60_000));
  const when = mins === 0 ? "just now" : `${mins} min ago`;
  const pairs = d.pairs.length;
  const what =
    d.mismatches === 0
      ? `all ${pairs} pair${pairs === 1 ? "" : "s"} match Alpaca paper`
      : `${d.mismatches} of ${pairs} pair${pairs === 1 ? "" : "s"} differ from Alpaca paper`;
  const failed = d.error && (d.failedAt ?? 0) > d.checkedAt ? ` (last read failed: ${d.error})` : "";
  return `Checked ${when}: ${what}${failed}`;
}

/** Sum of the fees booked as estimates, in dollars. */
export function estimatedFeeTotal(d: DemoReconcile): number {
  return d.estimatedFees.reduce((s, f) => s + f.usd, 0);
}

/**
 * A quantity with up to 9 decimals, trailing zeros dropped. A large one gets
 * fewer, so float noise past the 15th digit is never shown.
 */
export function qty9(x: number): string {
  const whole = Math.max(1, Math.floor(Math.log10(Math.max(1, Math.abs(x)))) + 1);
  const s = x.toFixed(Math.max(0, Math.min(9, 15 - whole)));
  return s.includes(".") ? s.replace(/\.?0+$/, "") : s;
}
