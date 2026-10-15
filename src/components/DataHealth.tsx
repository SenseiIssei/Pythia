import { Activity, Radio } from "lucide-react";
import { useStore } from "../store";
import { Badge } from "./ui";
import { Badge as CalmBadge, List, Notice } from "../design";
import { Section } from "../pagekit";
import { dataBadge } from "../pagekit/money";
import { KIND_LABEL, dataStatus, fmtAge, onFallback, sourceLabel } from "../dataHealth";
import type { KindHealth } from "../types";

/** The header's one-word data indicator. Hidden where no feeds run. */
export function DataHealthBadge() {
  const { dataHealth } = useStore();
  const s = dataStatus(dataHealth);
  if (!s) return null;
  return (
    <span className="hidden sm:inline-flex" aria-live="polite">
      <Badge tone={s.tone} title={s.detail}>
        <Activity size={11} aria-hidden className="mr-1" />
        {s.label}
      </Badge>
    </span>
  );
}

function names(ids: string[]): string {
  const short = ids.map((id) => id.split(":")[1] ?? id);
  return short.length > 4 ? `${short.slice(0, 3).join(", ")} and ${short.length - 3} more` : short.join(", ");
}

/** One kind of data (quotes, candles, books): where it comes from, how fresh, how much is stale. */
function KindRow({ k }: { k: KindHealth }) {
  const fallback = onFallback(k);
  const unused = k.sources.length === 0;
  return (
    <div className="flex items-start justify-between gap-3 py-3">
      <div className="min-w-0 flex-1">
        <div className="text-[15px] font-semibold text-ink">{KIND_LABEL[k.kind]}</div>
        {unused ? (
          <div className="text-[13px] text-muted">Calibrated defaults</div>
        ) : (
          <>
            <div className="break-words text-[13px] text-muted">
              <span className={fallback ? "font-semibold text-warn" : "text-ink"}>{sourceLabel(k.active)}</span>
              {fallback && <> (fallback; first choice {sourceLabel(k.primary)})</>}
            </div>
            <div className="mt-0.5 flex flex-wrap gap-x-2.5 text-[13px] text-muted">
              {k.sources.map((s) => (
                <span key={s.source} title={s.lastError ?? undefined} className={s.failStreak > 0 ? "text-down" : ""}>
                  {sourceLabel(s.source)} <span className="tabular">{s.markets}</span>
                  {s.failStreak > 0 ? ` (failing ${s.failStreak}x)` : ""}
                </span>
              ))}
            </div>
          </>
        )}
      </div>
      {!unused && (
        <div className="shrink-0 text-right">
          <div className="tabular text-[15px] font-semibold text-ink" title="Last update">
            {k.lastUpdateAgeSec == null ? "Never updated" : `${fmtAge(k.lastUpdateAgeSec)} old`}
          </div>
          {k.oldestUpdateAgeSec != null && k.oldestUpdateAgeSec !== k.lastUpdateAgeSec && (
            <div className="tabular text-[13px] text-muted">oldest {fmtAge(k.oldestUpdateAgeSec)}</div>
          )}
          <div className={`tabular text-[13px] ${k.stale.length > 0 ? "font-semibold text-down" : "text-muted"}`} title={names(k.stale)}>
            {k.stale.length}/{k.markets} stale
          </div>
          <div className={`tabular text-[13px] ${k.failovers24h > 0 ? "text-warn" : "text-muted"}`}>
            {k.failovers24h} failover{k.failovers24h === 1 ? "" : "s"} in 24 h
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Where the crypto data comes from right now, how fresh it is, and what the
 * feed layer refused. Shown on the Live page: a strategy that trades on its
 * own for days is only as good as the prices under it.
 */
export function DataHealthCard() {
  const { dataHealth: h } = useStore();
  if (!h || !h.running) return null;
  const s = dataStatus(h);
  const badge = dataBadge(s);
  const stream = h.stream;
  return (
    <Section
      title="Market data"
      help="Each kind of crypto data has a list of public venues. A market moves down the list when its source goes stale or fails, and back once the better one has delivered for a minute."
      hint="Where the crypto prices come from right now, and how fresh they are."
      right={badge && <CalmBadge tone={badge.tone}>{badge.word}</CalmBadge>}
    >
      {s && s.tone !== "green" && (
        <Notice tone={s.tone === "red" ? "danger" : "warning"} className="mb-3">
          {s.detail}
          {h.staleSince != null && (
            <span className="mt-1 block text-[13px]">
              Stale since {new Date(h.staleSince).toLocaleTimeString()}
              {h.alerted ? ", webhook alerted" : ""}.
            </span>
          )}
        </Notice>
      )}
      <List>
        {h.kinds.map((k) => (
          <KindRow key={k.kind} k={k} />
        ))}
      </List>
      {stream.enabled && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-line pt-3 text-[13px] text-muted">
          <Radio size={14} aria-hidden className={stream.connected ? "text-up" : "text-down"} />
          <span className="font-semibold text-ink">{sourceLabel(stream.source)}:</span>
          <span className="min-w-0 break-words">
            {stream.connected
              ? `connected${stream.since ? ` since ${new Date(stream.since).toLocaleTimeString()}` : ""}`
              : `down${stream.lastError ? ` (${stream.lastError})` : ""}, quotes are polled meanwhile`}
          </span>
          {stream.reconnects > 0 && <span className="text-faint">· {stream.reconnects} reconnects</span>}
        </div>
      )}
      {h.rejections.length > 0 && (
        <div className="mt-3 border-t border-line pt-3">
          <div className="text-[15px] font-semibold text-ink">Refused values</div>
          <ul className="mt-1 space-y-1 text-[13px] text-muted">
            {h.rejections.slice(0, 5).map((r) => (
              <li key={`${r.ts}-${r.market}-${r.source}`} className="break-words">
                <span className="tabular text-faint">{new Date(r.ts).toLocaleTimeString()}</span>{" "}
                {r.market.split(":")[1] ?? r.market} {KIND_LABEL[r.kind].toLowerCase()} from {sourceLabel(r.source)}: {r.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="mt-3 text-[13px] leading-relaxed text-faint">
        A quote far from every other venue is refused and never becomes the price. Stops and trims wait while a price is
        older than the staleness limit, and new entries are refused. A market whose candles change venue gets that
        venue's whole series and takes no entry on the switch bar.
      </p>
    </Section>
  );
}
