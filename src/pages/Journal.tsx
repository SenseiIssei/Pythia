import { useState } from "react";
import { ScrollText } from "lucide-react";
import { useStore } from "../store";
import { Card, PageHeader, Badge, EmptyState } from "../components/ui";
import type { JournalKind } from "../types";
import { TaxCard } from "../components/TaxCard";

const KINDS: { id: JournalKind | "all"; label: string; help: string }[] = [
  { id: "all", label: "All", help: "Everything, newest first." },
  { id: "signal", label: "Signals", help: "A strategy decided it wants to buy or sell." },
  { id: "order", label: "Orders", help: "An order was sent." },
  { id: "fill", label: "Fills", help: "An order was filled: the trade happened." },
  { id: "reject", label: "Refused", help: "An order was refused, with the reason." },
  { id: "risk", label: "Risk", help: "The risk manager stepped in or a limit changed." },
  { id: "system", label: "System", help: "Something about the engine itself." },
];

const kindTone: Record<string, string> = {
  signal: "text-purple-neon",
  fill: "text-success",
  reject: "text-danger",
  risk: "text-warning",
  order: "text-accent",
  system: "text-cyber-text-faint",
};

export function Journal() {
  const { journal } = useStore();
  const [filter, setFilter] = useState<JournalKind | "all">("all");
  const shown = journal.filter((e) => filter === "all" || e.kind === filter);

  return (
    <div className="animate-fade-in mx-auto max-w-6xl space-y-4">
      <PageHeader
        title="Journal"
        subtitle="An append-only record of every signal, order, fill and refusal, so anything that happened can be traced afterwards."
      />

      <TaxCard />

      <div role="radiogroup" aria-label="Show entries" className="flex flex-wrap gap-1.5">
        {KINDS.map((k) => (
          <button
            key={k.id}
            type="button"
            role="radio"
            aria-checked={filter === k.id}
            title={k.help}
            onClick={() => setFilter(k.id)}
            className={`rounded-lg border px-3 py-1 text-xs font-medium transition-colors ${
              filter === k.id
                ? "border-accent/40 bg-accent/10 text-accent"
                : "border-cyber-border text-cyber-text-dim hover:border-cyber-border-bright hover:text-cyber-text"
            }`}
          >
            {k.label}
          </button>
        ))}
      </div>

      <Card>
        {shown.length === 0 ? (
          <EmptyState icon={ScrollText} title="No entries of this kind yet" compact />
        ) : (
          <ul className="max-h-[calc(100dvh-300px)] min-h-[200px] divide-y divide-cyber-border/50 overflow-y-auto text-xs">
            {shown.map((e) => (
              <li key={e.id} className="flex flex-wrap items-start gap-x-2 gap-y-0.5 py-1.5 sm:flex-nowrap">
                <span className="w-20 shrink-0 font-mono text-cyber-text-faint">{new Date(e.ts).toLocaleTimeString()}</span>
                <span
                  title={KINDS.find((k) => k.id === e.kind)?.help}
                  className={`w-14 shrink-0 font-mono uppercase ${kindTone[e.kind] ?? "text-cyber-text-faint"}`}
                >
                  {e.kind}
                </span>
                {e.mode === "live" && <Badge tone="red">live</Badge>}
                <span className="min-w-0 basis-full break-words text-cyber-text-dim sm:basis-auto">{e.message}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
