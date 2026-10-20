import { useCallback, useEffect, useState } from "react";
import { CreditCard, RefreshCw, ShieldCheck } from "lucide-react";
import { Badge, Button, Card, Field, Meter, Notice, inputCls } from "./ui";
import {
  JOB_LABELS,
  aiBudget,
  capsNote,
  jobSpendTable,
  parseCap,
  setAiBudget,
  usd,
  usedShare,
  type AiBudget,
  type AiCaps,
} from "../aiBudget";
import { liveMode } from "../live";

type CapKey = keyof AiCaps;

const CAPS: { key: CapKey; label: string; hint: string }[] = [
  { key: "lifetimeUsd", label: "Lifetime cap (USD)", hint: "All calls ever. Telegram alerts at 50, 80 and 100 %." },
  { key: "monthlyUsd", label: "Monthly cap (USD)", hint: "This calendar month, UTC." },
  { key: "dailyUsd", label: "Daily cap (USD)", hint: "Today, UTC." },
];

const fmtTime = (ms: number) => new Date(ms).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

/**
 * The hard budget in front of every Claude API call: what has been spent
 * against each cap, the caps themselves, and the last calls from the ledger.
 */
export function AiBudgetCard() {
  const mode = liveMode();
  const [b, setB] = useState<AiBudget | null>(null);
  const [draft, setDraft] = useState<Record<CapKey, string>>({ lifetimeUsd: "", monthlyUsd: "", dailyUsd: "" });
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const v = await aiBudget();
      setB(v);
      setDraft({
        lifetimeUsd: String(v.caps.lifetimeUsd),
        monthlyUsd: String(v.caps.monthlyUsd),
        dailyUsd: String(v.caps.dailyUsd),
      });
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (mode !== "none") void load();
  }, [mode, load]);

  if (mode === "none") return null;

  const parsed = Object.fromEntries(CAPS.map((c) => [c.key, parseCap(draft[c.key])])) as Record<CapKey, number | string>;
  const invalid = CAPS.find((c) => typeof parsed[c.key] === "string");
  const next: AiCaps | null = invalid
    ? null
    : { lifetimeUsd: parsed.lifetimeUsd as number, monthlyUsd: parsed.monthlyUsd as number, dailyUsd: parsed.dailyUsd as number };
  const changed = !!(b && next && (next.lifetimeUsd !== b.caps.lifetimeUsd || next.monthlyUsd !== b.caps.monthlyUsd || next.dailyUsd !== b.caps.dailyUsd));
  const note = next ? capsNote(next) : null;

  async function save(caps: AiCaps) {
    setBusy(true);
    setMsg("");
    try {
      const v = await setAiBudget(caps);
      setB(v);
      setDraft({ lifetimeUsd: String(v.caps.lifetimeUsd), monthlyUsd: String(v.caps.monthlyUsd), dailyUsd: String(v.caps.dailyUsd) });
      setMsg("Caps saved. They apply to the next call.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  }

  const perJob = b ? jobSpendTable(b.byJobDay, b.spend.day) : null;

  const meters = b
    ? [
        { label: "Lifetime", spent: b.spend.lifetimeUsd, cap: b.caps.lifetimeUsd, sub: `${b.spend.calls.toLocaleString("en-US")} calls` },
        { label: `This month (${b.spend.month})`, spent: b.spend.monthUsd, cap: b.caps.monthlyUsd, sub: "" },
        { label: "Today", spent: b.spend.todayUsd, cap: b.caps.dailyUsd, sub: `${b.spend.callsToday} calls` },
      ]
    : [];

  return (
    <Card
      title="Claude API budget"
      icon={CreditCard}
      help="A hard limit on what the Claude API may cost. Every call checks the ledger first and is refused, before anything is sent, when it would cross a cap."
      subtitle={
        b ? (
          <>
            Own models first; Claude reads and writes for you: {b.models.routine} for the strategy critic and routine calls,{" "}
            {b.models.review} for the daily brief, the weekly review and your Telegram questions, {b.models.deep} for the
            weekly research director. Prices as of {b.pricesAsOf}
            {b.pricesEstimate ? " (estimates)" : ""}.
          </>
        ) : (
          "Every Claude call is checked against these caps first."
        )
      }
      right={
        <>
          {b && <Badge tone={b.keyConfigured ? "green" : "neutral"}>{b.keyConfigured ? "key set" : "no key"}</Badge>}
          <Button size="sm" tone="neutral" icon={RefreshCw} onClick={() => void load()} ariaLabel="Reload the budget">
            Reload
          </Button>
        </>
      }
    >
      {err && (
        <Notice tone="danger" title="Could not read the budget">
          {err}
        </Notice>
      )}

      {b?.refusing && (
        <Notice tone="warning" title="Calls are refused right now">
          {b.refusing}
        </Notice>
      )}

      {b && !b.persisted && (
        <Notice tone="warning" title="The ledger is kept in memory only">
          No data folder, so spend is forgotten on restart. Set PYTHIA_DATA or PYTHIA_AI_DIR on the server.
        </Notice>
      )}

      {b && (
        <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
          {meters.map((m) => {
            const share = usedShare(m.spent, m.cap);
            return (
              <div key={m.label} className="min-w-0">
                <div className="mb-1 flex items-baseline justify-between gap-2 text-[13px]">
                  <span className="text-muted">{m.label}</span>
                  <span className="tabular font-semibold text-ink">
                    {usd(m.spent)} <span className="font-normal text-muted">of {usd(m.cap)}</span>
                  </span>
                </div>
                <Meter pct={share * 100} tone={share >= 1 ? "red" : share >= 0.8 ? "amber" : "cyan"} label={`${m.label} budget used`} />
                {m.sub && <div className="mt-1 text-[12px] text-faint">{m.sub}</div>}
              </div>
            );
          })}
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {CAPS.map((c) => (
          <Field key={c.key} label={c.label} hint={typeof parsed[c.key] === "string" && draft[c.key] !== "" ? (parsed[c.key] as string) : c.hint}>
            <input
              inputMode="decimal"
              value={draft[c.key]}
              onChange={(e) => setDraft((d) => ({ ...d, [c.key]: e.target.value }))}
              className={inputCls}
              aria-invalid={typeof parsed[c.key] === "string"}
            />
          </Field>
        ))}
      </div>
      {note && <div className="mt-2 text-[13px] text-warn">{note}</div>}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button icon={ShieldCheck} disabled={busy || !changed || !next} onClick={() => next && void save(next)}>
          Save caps
        </Button>
        {b && (
          <Button tone="neutral" disabled={busy} onClick={() => void save(b.defaults)}>
            Defaults ({usd(b.defaults.lifetimeUsd)} / {usd(b.defaults.monthlyUsd)} / {usd(b.defaults.dailyUsd)})
          </Button>
        )}
        {msg && (
          <span role="status" className="text-xs text-success">
            {msg}
          </span>
        )}
      </div>

      {perJob && perJob.rows.length > 0 && (
        <div className="mt-5">
          <div className="mb-2 flex items-baseline justify-between gap-2">
            <span className="text-[13px] font-semibold text-ink">Spend per job</span>
            <span className="text-[12px] text-faint">
              last 7 days (UTC): {usd(perJob.total)}, {usd(perJob.total / perJob.days.length)} a day
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] text-left text-[13px]" aria-label="Claude API spend per job and day">
              <thead className="text-muted">
                <tr>
                  <th className="py-1 pr-3 font-medium">Job</th>
                  {perJob.days.map((d) => (
                    <th key={d} className="py-1 pr-2 text-right font-medium">
                      {d.slice(5)}
                    </th>
                  ))}
                  <th className="py-1 text-right font-medium">7 days</th>
                </tr>
              </thead>
              <tbody className="tabular text-ink">
                {perJob.rows.map((r) => (
                  <tr key={r.job} className="border-t border-line">
                    <td className="py-1 pr-3 whitespace-nowrap" title={`${r.calls} calls`}>
                      {JOB_LABELS[r.job] ?? r.job}
                    </td>
                    {r.perDay.map((v, i) => (
                      <td key={perJob.days[i]} className={`py-1 pr-2 text-right ${v ? "" : "text-faint"}`}>
                        {v ? usd(v) : "–"}
                      </td>
                    ))}
                    <td className="py-1 text-right font-semibold">{usd(r.total)}</td>
                  </tr>
                ))}
                <tr className="border-t border-line text-muted">
                  <td className="py-1 pr-3">All jobs</td>
                  {perJob.dayTotals.map((v, i) => (
                    <td key={perJob.days[i]} className="py-1 pr-2 text-right">
                      {v ? usd(v) : "–"}
                    </td>
                  ))}
                  <td className="py-1 text-right font-semibold text-ink">{usd(perJob.total)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}

      {b && b.recent.length > 0 && (
        <div className="mt-5">
          <div className="mb-2 text-[13px] font-semibold text-ink">Last calls</div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-[13px]">
              <thead className="text-muted">
                <tr>
                  <th className="py-1 pr-3 font-medium">When</th>
                  <th className="py-1 pr-3 font-medium">Job</th>
                  <th className="py-1 pr-3 font-medium">Model</th>
                  <th className="py-1 pr-3 text-right font-medium">Tokens in / out</th>
                  <th className="py-1 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody className="tabular text-ink">
                {b.recent.slice(0, 10).map((e, i) => (
                  <tr key={`${e.ts}-${i}`} className="border-t border-line">
                    <td className="py-1 pr-3 whitespace-nowrap">{fmtTime(e.ts)}</td>
                    <td className="py-1 pr-3">
                      {e.job}
                      {e.batch ? " (batch)" : ""}
                      {!e.ok ? " (no answer)" : ""}
                    </td>
                    <td className="py-1 pr-3">{e.servedBy || e.model}</td>
                    <td className="py-1 pr-3 text-right">
                      {(e.inputTokens + e.cacheReadTokens + e.cacheWriteTokens).toLocaleString("en-US")} / {e.outputTokens.toLocaleString("en-US")}
                    </td>
                    <td className="py-1 text-right">{usd(e.costUsd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}
