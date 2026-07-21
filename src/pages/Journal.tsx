import { useState } from "react";
import { useStore } from "../store";
import { Card, PageHeader, Badge } from "../components/ui";
import type { JournalKind } from "../types";

const KINDS: (JournalKind | "all")[] = ["all", "signal", "order", "fill", "reject", "risk", "system"];

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
    <div className="animate-fade-in">
      <PageHeader
        title="Journal"
        subtitle="Append-only audit log — every signal, order, fill & rejection"
      />

      <div className="mb-4 flex gap-2">
        {KINDS.map((k) => (
          <button
            key={k}
            onClick={() => setFilter(k)}
            className={`rounded-lg border px-3 py-1 text-xs uppercase transition-colors ${
              filter === k
                ? "border-accent/40 bg-accent/10 text-accent"
                : "border-cyber-border text-cyber-text-dim hover:text-cyber-text"
            }`}
          >
            {k}
          </button>
        ))}
      </div>

      <Card>
        <div className="max-h-[calc(100vh-260px)] space-y-1 overflow-y-auto font-mono text-xs">
          {shown.length === 0 && <div className="text-cyber-text-faint">No entries.</div>}
          {shown.map((e) => (
            <div key={e.id} className="flex items-start gap-2 border-b border-cyber-border/40 py-1">
              <span className="w-20 shrink-0 text-cyber-text-faint">
                {new Date(e.ts).toLocaleTimeString()}
              </span>
              <span className={`w-14 shrink-0 uppercase ${kindTone[e.kind] ?? "text-cyber-text-faint"}`}>
                {e.kind}
              </span>
              {e.mode === "live" && <Badge tone="red">live</Badge>}
              <span className="text-cyber-text-dim">{e.message}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
