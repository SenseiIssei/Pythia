import { Banknote, ChevronRight } from "lucide-react";
import { openPage } from "../navigate";

/**
 * Where the Autopilot page showed its real-money group: one line to the Real
 * money page, which has everything that trades real money.
 */
export function RealMoneyLink({ count }: { count: number }) {
  return (
    <button
      type="button"
      onClick={() => openPage("realmoney")}
      className="flex w-full items-center gap-3 rounded-card border border-line bg-surface px-4 py-3 text-left transition-colors hover:bg-surface-2"
    >
      <Banknote size={18} aria-hidden className="shrink-0 text-down" />
      <span className="min-w-0 flex-1">
        <span className="block text-[15px] font-semibold text-ink">Real money</span>
        <span className="block text-[13px] text-muted">
          {count > 0 ? `${count} real-money autopilot${count === 1 ? "" : "s"} running. ` : ""}Everything with real money has its own page.
        </span>
      </span>
      <ChevronRight size={17} aria-hidden className="shrink-0 text-faint" />
    </button>
  );
}
