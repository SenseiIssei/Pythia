import { useEffect, useState } from "react";
import { ArrowDownLeft, ArrowUpRight, Bell, FileText, History, Plane, Repeat, ShieldAlert, XCircle, type LucideIcon } from "lucide-react";
import { Card, Chip, Empty, ListRow, Page, Segmented, Skeleton } from "../design/flows";
import { timeOfDay, timeline, type ActivityFilter, type ActivityKind } from "../flows/activity";
import { alertsAvailable, fetchAlerts, fetchEvents, type AlertsView } from "../flows/alerts";
import { useStore } from "../store";
import type { JournalEntry } from "../types";

const ICON: Record<ActivityKind, LucideIcon> = {
  buy: ArrowDownLeft,
  sell: ArrowUpRight,
  rebalance: Repeat,
  autopilot: Plane,
  alert: Bell,
  risk: ShieldAlert,
  refused: XCircle,
  summary: FileText,
};

/** The events ring changes with every trade, but a minute is plenty for a timeline. */
const REFRESH_MS = 60_000;

/**
 * Everything that happened, newest first and grouped by day: fills,
 * rebalances, autopilot changes, alerts and the daily report.
 */
export function Activity() {
  const { journal, markets } = useStore();
  const [filter, setFilter] = useState<ActivityFilter>("all");
  const [events, setEvents] = useState<JournalEntry[] | null>(null);
  const [alerts, setAlerts] = useState<AlertsView | null>(null);
  const [loaded, setLoaded] = useState(!alertsAvailable());
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!alertsAvailable()) return;
    let gone = false;
    const read = async () => {
      const [ev, al] = await Promise.all([fetchEvents(), fetchAlerts()]);
      if (gone) return;
      if (ev.ok) setEvents(ev.data);
      if (al.ok) setAlerts(al.data);
      setLoaded(true);
      setNow(Date.now());
    };
    void read();
    const t = setInterval(() => void read(), REFRESH_MS);
    return () => {
      gone = true;
      clearInterval(t);
    };
  }, []);

  const days = timeline(
    { events: events ?? [], journal, alerts: alerts?.recent, digest: alerts?.lastDigest, markets },
    now,
    filter,
  );

  return (
    <Page title="Activity">
      <Segmented
        label="Show"
        value={filter}
        onChange={setFilter}
        options={[
          { id: "all", label: "All" },
          { id: "trades", label: "Trades" },
          { id: "alerts", label: "Alerts" },
        ]}
      />

      {!loaded ? (
        <Card>
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center gap-3 py-3">
              <Skeleton className="h-10 w-10 rounded-full" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-3 w-3/4" />
              </div>
            </div>
          ))}
        </Card>
      ) : days.length === 0 ? (
        <Card>
          <Empty icon={History} title="Nothing yet">
            Trades, rebalances and alerts show up here as they happen.
          </Empty>
        </Card>
      ) : (
        days.map((d) => (
          <section key={d.key} aria-label={d.label}>
            <div className="flex items-baseline justify-between gap-2 px-1 pb-1 pt-2">
              <h2 className="text-lg font-semibold tracking-tight">{d.label}</h2>
              {d.summary && <span className="fl-muted text-sm">{d.summary}</span>}
            </div>
            <Card className="py-1">
              <ul className="divide-y divide-line">
                {d.items.map((it) => (
                  <li key={it.id}>
                    <ListRow
                      icon={ICON[it.kind]}
                      title={it.title}
                      subtitle={it.detail}
                      right={it.amount}
                      rightSub={
                        <span className="fl-muted inline-flex items-center gap-1.5">
                          {it.real && <Chip tone="bad">Real</Chip>}
                          {timeOfDay(it.ts)}
                        </span>
                      }
                    />
                  </li>
                ))}
              </ul>
            </Card>
          </section>
        ))
      )}
    </Page>
  );
}
