import { useEffect, useState } from "react";
import { Card } from "../design";
import { liveMode } from "../live";
import { labStatus } from "../lab";
import { ago, feedTone, labFeeds, pickInsights, type Insight } from "../labFeeds";
import { openPage } from "../navigate";
import { isVisible } from "../nav";
import { useUiMode } from "../uiMode";

/** Refresh the insights this often while the page is open. */
const REFRESH_MS = 10 * 60_000;

/**
 * The lab's insights for today, from the feeds, the forward report and the
 * learning loop. `null` while loading or where there is no engine to ask;
 * failures count as "nothing to say" so Home never alarms over a lab hiccup.
 */
export function useLabInsights(): { insights: Insight[] | null; available: boolean } {
  const available = liveMode() !== "none";
  const [insights, setInsights] = useState<Insight[] | null>(null);
  useEffect(() => {
    if (!available) return;
    let alive = true;
    const load = async () => {
      const [feeds, status] = await Promise.all([labFeeds().catch(() => []), labStatus().catch(() => null)]);
      if (alive) setInsights(pickInsights(feeds, status?.forward ?? null, status?.learn ?? null, Date.now()));
    };
    void load();
    const t = window.setInterval(() => void load(), REFRESH_MS);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [available]);
  return { insights, available };
}

const DOT = { green: "bg-up", amber: "bg-warn", red: "bg-down", neutral: "bg-faint" } as const;

/**
 * Three lines at most: what happened, where it comes from, how long ago.
 * Colours come from the surrounding text (muted parts by opacity), so the list
 * reads the same on Home's card and on the calm Research page.
 */
export function InsightList({ insights, now = Date.now() }: { insights: Insight[]; now?: number }) {
  return (
    <ol>
      {insights.map((x, i) => {
        const t = feedTone(x.status);
        return (
          <li
            key={`${x.source}:${x.text}`}
            className={`flex gap-3 py-3 first:pt-0 last:pb-0 ${i > 0 ? "border-t" : ""}`}
            style={i > 0 ? { borderTopColor: "color-mix(in srgb, currentColor 12%, transparent)" } : undefined}
          >
            <span aria-label={t.label} className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT[t.tone]}`} />
            <div className="min-w-0">
              <div className="text-[15px] font-medium leading-snug">{x.text}</div>
              {x.detail && <div className="mt-0.5 text-sm leading-relaxed opacity-75">{x.detail}</div>}
              <div className="mt-1 text-xs opacity-60">
                {x.title}
                {x.atMs ? ` · ${ago(x.atMs, now)}` : ""}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** Home's card: the three most important things from the lab today. Hidden without an engine. */
export function InsightsCard() {
  const { insights, available } = useLabInsights();
  const mode = useUiMode();
  if (!available || insights === null) return null;
  const canOpen = isVisible("research", mode);
  return (
    <section aria-labelledby="lab-today" className="space-y-2">
      <div className="flex items-baseline justify-between gap-2 px-1 pt-3">
        <h2 id="lab-today" className="text-xl font-semibold tracking-tight text-ink">
          Today in the lab
        </h2>
        {canOpen && (
          <button type="button" onClick={() => openPage("research")} className="rounded text-[15px] font-semibold text-accent hover:underline">
            All research
          </button>
        )}
      </div>
      <Card>
        {insights.length === 0 ? (
          <p className="text-[15px] text-muted">All quiet. Nothing in the lab needs your attention today.</p>
        ) : (
          <div className="text-ink">
            <InsightList insights={insights} />
          </div>
        )}
      </Card>
    </section>
  );
}
