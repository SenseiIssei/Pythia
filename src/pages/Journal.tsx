import { useMemo, useState } from "react";
import { ScrollText } from "lucide-react";
import { useStore } from "../store";
import { Card, Chip, FilterChips, KeyStats, Nothing, PageShell, Section, type ChipOption } from "../pagekit";
import { JOURNAL_KINDS, filterJournal, isDemoLine, journalCounts, kindInfo, type JournalFilter } from "../pagekit/journal";
import { TaxCard } from "../components/TaxCard";
import type { JournalKind } from "../types";

const ORDER: JournalKind[] = ["fill", "order", "signal", "reject", "risk", "system"];

/** Long lists stay quick: the newest lines first, more on request. */
const PAGE = 200;

export function Journal() {
  const { journal } = useStore();
  const [filter, setFilter] = useState<JournalFilter>("all");
  const [limit, setLimit] = useState(PAGE);
  const counts = useMemo(() => journalCounts(journal), [journal]);
  const shown = filterJournal(journal, filter);

  const options: ChipOption<JournalFilter>[] = [
    { id: "all", label: "All", help: "Everything, newest first.", count: counts.all },
    ...ORDER.map((k) => ({ id: k, label: JOURNAL_KINDS[k].label, help: JOURNAL_KINDS[k].help, count: counts[k] })),
  ];

  return (
    <PageShell
      title="Journal"
      subtitle="A record of every signal, order, fill and refusal that is only ever added to, so anything that happened can be traced afterwards."
    >
      <KeyStats
        items={[
          { label: "Entries", value: counts.all.toLocaleString("en-US"), help: "Lines in the journal this session." },
          { label: "Filled", value: counts.fill.toLocaleString("en-US"), help: "Orders that turned into trades." },
          { label: "Refused", value: counts.reject.toLocaleString("en-US"), tone: counts.reject > 0 ? "warn" : "plain", help: "Orders the venue or the risk manager turned down." },
        ]}
      />

      <TaxCard />

      <Section title="Entries" hint="Tap a filter to see one kind. The newest is at the top." bare>
        <FilterChips
          label="Show entries"
          options={options}
          value={filter}
          onChange={(f) => {
            setFilter(f);
            setLimit(PAGE);
          }}
        />
        <Card>
          {shown.length === 0 ? (
            <Nothing icon={ScrollText} title="No entries of this kind yet" />
          ) : (
            <ul className="pk-rows">
              {shown.slice(0, limit).map((e) => {
                const k = kindInfo(e.kind);
                return (
                  <li key={e.id} className="py-3">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Chip tone={k.tone} title={k.help}>
                        {k.label}
                      </Chip>
                      {e.mode === "live" && <Chip tone="bad">Live</Chip>}
                      {isDemoLine(e) && <Chip>Demo</Chip>}
                      <span className="fl-muted fl-num ml-auto text-sm">{new Date(e.ts).toLocaleTimeString()}</span>
                    </div>
                    <p className="mt-1 break-words text-[15px]">{e.message}</p>
                  </li>
                );
              })}
            </ul>
          )}
          {shown.length > limit && (
            <button type="button" onClick={() => setLimit((l) => l + PAGE)} className="fl-focus pk-link mt-2 w-full py-2 text-center text-[15px]">
              Show {Math.min(PAGE, shown.length - limit)} more of {shown.length - limit}
            </button>
          )}
        </Card>
      </Section>
    </PageShell>
  );
}
