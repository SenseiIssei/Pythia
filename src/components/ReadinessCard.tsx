import { useEffect, useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import { Badge, Card } from "../design";
import { liveMode } from "../live";
import { labStatus } from "../lab";
import {
  RULE_SHORT,
  ordered,
  parseReadiness,
  profileFor,
  profileWords,
  progressWords,
  readinessSettings,
  setReadinessSettings,
  type ReadinessItem,
  type ReadinessReport,
} from "../readiness";

/** Refresh while the page is open; the check itself runs once a day. */
const REFRESH_MS = 15 * 60_000;

/**
 * Real money readiness: per autopilot on the Alpaca paper account, which of
 * the pre-registered rules pass and how many days are left, plus the risk
 * slider. Reads the lab's daily check; it never arms or changes anything.
 * Hidden without an engine to ask.
 */
export function ReadinessCard() {
  const available = liveMode() !== "none";
  const [report, setReport] = useState<ReadinessReport | null | undefined>(undefined);
  const [step, setStep] = useState<number | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    if (!available) return;
    let alive = true;
    const load = async () => {
      const [status, settings] = await Promise.all([labStatus().catch(() => null), readinessSettings().catch(() => null)]);
      if (!alive) return;
      setReport(parseReadiness(status?.readiness ?? null));
      if (settings) setStep(settings.riskStep);
    };
    void load();
    const t = window.setInterval(() => void load(), REFRESH_MS);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [available]);

  if (!available || report === undefined) return null;

  if (report === null) {
    return (
      <Card title="Real money readiness">
        <p className="text-sm leading-relaxed text-muted">
          The daily check has not run yet. Once it has, this shows for every autopilot on the Alpaca paper account which of the real money
          rules it meets and how many days are left.
        </p>
      </Card>
    );
  }

  const shown = step ?? report.profile.step;
  const chosen = profileFor(report.profiles, shown) ?? report.profile;
  const items = ordered(report.items);
  const ready = items.filter((i) => i.ready && i.onAccount).length;

  async function choose(next: number) {
    const before = step;
    setStep(next);
    setSaving("Saving…");
    try {
      const s = await setReadinessSettings(next);
      setStep(s.riskStep);
      setSaving("Saved. The next daily check uses it.");
    } catch (e) {
      setStep(before);
      setSaving(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <Card
      title="Real money readiness"
      right={<Badge tone={ready ? "good" : "neutral"}>{ready ? `${ready} ready` : "none ready"}</Badge>}
    >
      <p className="text-sm leading-relaxed text-muted">
        Real money only once an autopilot makes money steadily on the Alpaca paper account, after fees. Rule of {report.ruleDate || "?"}.
        Nothing here arms live: when one meets every rule you get a message, and only you can arm it.
      </p>

      {items.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No autopilot runs on the Alpaca paper account yet.</p>
      ) : (
        <ul className="mt-3 divide-y divide-line">
          {items.map((i) => (
            <ItemRow key={i.key} i={i} />
          ))}
        </ul>
      )}

      <div className="mt-4 border-t border-line pt-4">
        <div className="flex items-start justify-between gap-3">
          <label htmlFor="readiness-risk" className="text-[15px] text-ink">
            Risk
          </label>
          <div className="text-right text-[15px] font-semibold capitalize text-ink">
            {chosen.label} ({shown} of 5)
          </div>
        </div>
        <input
          id="readiness-risk"
          type="range"
          min={1}
          max={5}
          step={1}
          value={shown}
          aria-valuetext={`${chosen.label}: ${profileWords(chosen)}`}
          disabled={step == null}
          onChange={(e) => void choose(Number(e.target.value))}
          className="mt-3 w-full min-w-0 accent-accent"
        />
        <div className="mt-1 flex justify-between text-xs text-muted">
          <span>careful</span>
          <span>bold</span>
        </div>
        <p className="tabular mt-2 text-sm text-ink" data-testid="readiness-profile">
          {profileWords(chosen)}
        </p>
        {saving && <p className="mt-1 text-xs text-muted">{saving}</p>}
        {step == null && <p className="mt-1 text-xs text-muted">The setting can be changed with the engine connected.</p>}
        <p className="mt-2 text-xs leading-relaxed text-muted">
          Inflation used: {report.inflation.pct != null ? `${report.inflation.pct.toFixed(1)} %` : "unknown"}
          {report.inflation.source ? ` (${report.inflation.source}, ${report.inflation.month}${report.inflation.cached ? ", last known figure" : ""})` : ""}.
          Returns are annualised to compare with inflation and the ETF hurdle; over 30 to 45 days that number is noisy, one lucky month
          looks like a great year. That is why steady weeks and a shallow drawdown count too.
        </p>
      </div>
    </Card>
  );
}

function ItemRow({ i }: { i: ReadinessItem }) {
  const sleeve = i.kind === "sleeve";
  return (
    <li className={`py-3 first:pt-0 last:pb-0 ${sleeve ? "pl-4" : ""}`}>
      <div className="flex items-center justify-between gap-3">
        <div className={`min-w-0 truncate ${sleeve ? "text-sm text-muted" : "text-[15px] font-medium text-ink"}`}>{i.name}</div>
        <Badge tone={i.ready ? "good" : i.onAccount ? "warn" : "neutral"}>
          {i.ready ? "ready" : `${i.passed} of ${i.total}`}
        </Badge>
      </div>
      <div className="mt-0.5 text-xs text-muted">
        {progressWords(i)}
        {i.annualisedPct != null && ` · ${i.annualisedPct >= 0 ? "+" : ""}${i.annualisedPct.toFixed(1)} % a year`}
        {i.sp500Pct != null && ` · S&P 500 ${i.sp500Pct >= 0 ? "+" : ""}${i.sp500Pct.toFixed(1)} % over the same days`}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
        {i.rules.map((r) => {
          const Icon = r.pass ? CheckCircle2 : XCircle;
          return (
            <li
              key={r.id}
              title={`${r.label}: ${r.value} (needs ${r.need})${r.detail ? `. ${r.detail}` : ""}`}
              className={`inline-flex items-center gap-1 text-xs ${r.pass ? "text-up" : "text-muted"}`}
            >
              <Icon size={13} aria-hidden />
              <span>{RULE_SHORT[r.id] ?? r.label}</span>
              <span className="sr-only">{r.pass ? "passes" : "not yet"}</span>
            </li>
          );
        })}
      </ul>
    </li>
  );
}
