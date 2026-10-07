import { Activity, Radio } from "lucide-react";
import { useStore } from "../store";
import { Badge, Card, Notice } from "./ui";
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

function KindRow({ k }: { k: KindHealth }) {
  const fallback = onFallback(k);
  const unused = k.sources.length === 0;
  return (
    <tr className="border-t border-cyber-border/50 align-top">
      <td className="py-1.5 pr-2 font-medium">{KIND_LABEL[k.kind]}</td>
      <td className="py-1.5 pr-2">
        {unused ? (
          <span className="text-cyber-text-faint">calibrated defaults</span>
        ) : (
          <>
            <span className={fallback ? "text-warning" : "text-cyber-text"}>{sourceLabel(k.active)}</span>
            {fallback && <span className="text-cyber-text-faint"> (first choice {sourceLabel(k.primary)})</span>}
            <div className="mt-0.5 flex flex-wrap gap-x-2 text-[10px] text-cyber-text-faint">
              {k.sources.map((s) => (
                <span key={s.source} title={s.lastError ?? undefined} className={s.failStreak > 0 ? "text-danger" : ""}>
                  {sourceLabel(s.source)} {s.markets}
                  {s.failStreak > 0 ? ` (failing ${s.failStreak}x)` : ""}
                </span>
              ))}
            </div>
          </>
        )}
      </td>
      <td className="py-1.5 pr-2 text-right font-mono">
        {unused ? "" : fmtAge(k.lastUpdateAgeSec)}
        {!unused && k.oldestUpdateAgeSec != null && k.oldestUpdateAgeSec !== k.lastUpdateAgeSec && (
          <div className="text-[10px] text-cyber-text-faint">oldest {fmtAge(k.oldestUpdateAgeSec)}</div>
        )}
      </td>
      <td className={`py-1.5 pr-2 text-right font-mono ${k.failovers24h > 0 ? "text-warning" : ""}`}>{k.failovers24h}</td>
      <td className={`py-1.5 text-right font-mono ${k.stale.length > 0 ? "text-danger" : "text-success"}`} title={names(k.stale)}>
        {k.stale.length}/{k.markets}
      </td>
    </tr>
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
  const stream = h.stream;
  return (
    <Card
      title="Market data"
      icon={Activity}
      className="mb-4"
      help="Each kind of crypto data has a list of public venues. A market moves down the list when its source goes stale or fails, and back once the better one has delivered for a minute."
      right={s && <Badge tone={s.tone}>{s.label}</Badge>}
    >
      {s && s.tone !== "green" && (
        <Notice tone={s.tone === "red" ? "danger" : "warning"} className="mb-3">
          {s.detail}
          {h.staleSince != null && (
            <span className="block text-[11px] text-cyber-text-faint">
              Stale since {new Date(h.staleSince).toLocaleTimeString()}
              {h.alerted ? ", webhook alerted" : ""}.
            </span>
          )}
        </Notice>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-widest text-cyber-text-faint">
              <th className="py-1 text-left font-normal">Data</th>
              <th className="py-1 text-left font-normal">Source, markets per source</th>
              <th className="py-1 text-right font-normal">Updated</th>
              <th className="py-1 text-right font-normal">Failovers 24 h</th>
              <th className="py-1 text-right font-normal">Stale</th>
            </tr>
          </thead>
          <tbody>
            {h.kinds.map((k) => (
              <KindRow key={k.kind} k={k} />
            ))}
          </tbody>
        </table>
      </div>
      {stream.enabled && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-cyber-text-dim">
          <Radio size={12} aria-hidden className={stream.connected ? "text-success" : "text-danger"} />
          {sourceLabel(stream.source)}:{" "}
          {stream.connected
            ? `connected${stream.since ? ` since ${new Date(stream.since).toLocaleTimeString()}` : ""}`
            : `down${stream.lastError ? ` (${stream.lastError})` : ""}, quotes are polled meanwhile`}
          {stream.reconnects > 0 && <span className="text-cyber-text-faint">· {stream.reconnects} reconnects</span>}
        </div>
      )}
      {h.rejections.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-[10px] uppercase tracking-widest text-cyber-text-faint">Refused values</div>
          <ul className="space-y-0.5 text-[11px] text-cyber-text-dim">
            {h.rejections.slice(0, 5).map((r) => (
              <li key={`${r.ts}-${r.market}-${r.source}`} className="break-words">
                <span className="font-mono text-cyber-text-faint">{new Date(r.ts).toLocaleTimeString()}</span>{" "}
                {r.market.split(":")[1] ?? r.market} {KIND_LABEL[r.kind].toLowerCase()} from {sourceLabel(r.source)}: {r.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-3 text-[11px] leading-snug text-cyber-text-faint">
        A quote far from every other venue is refused and never becomes the price. Stops and trims wait while a
        price is older than the staleness limit, and new entries are refused. A market whose candles change venue
        gets that venue's whole series and takes no entry on the switch bar.
      </div>
    </Card>
  );
}
