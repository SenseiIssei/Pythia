// The model zoo on the Models page: every model the lab keeps, one row each,
// its edge over its baseline out of sample on the right. A row opens a sheet
// with the score against the baseline over time, live shadow, the last
// retrain, drift and who uses it. Read-only.

import { useState } from "react";
import { AreaChart, Badge, List, ListRow, Notice, Sheet, Sparkline, signedPct } from "../design";
import { More, Row, Section, num, plural, share } from "../pagekit";
import {
  METRIC_WORDS,
  ago,
  driftChip,
  edgeNow,
  edgePoints,
  fmtP,
  fmtScore,
  needsAttention,
  statusTone,
  statusWord,
  winShare,
  type ZooModel,
  type ZooStatus,
} from "../zoo";

const tone = (v: number | null) => (v === null ? "plain" : v > 0 ? "up" : v < 0 ? "down" : "plain");
const toneText = { up: "text-up", down: "text-down", plain: "text-ink" } as const;

function CodeMark({ code }: { code: string }) {
  return (
    <span aria-hidden className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[13px] font-semibold text-ink">
      {code}
    </span>
  );
}

function retrainWords(m: ZooModel): string {
  if (m.managedBy === "retired") return "retired";
  if (m.managedBy === "learn") return `retrained by the nightly loop, ${ago(m.lastRetrainMs)}`;
  return `retrained ${ago(m.lastRetrainMs)}`;
}

/** Every model the lab keeps, with the sheet that opens on a row. */
export function ModelZoo({ z }: { z: ZooStatus }) {
  const [open, setOpen] = useState<string | null>(null);
  const shown = z.models.find((m) => m.code === open) ?? null;
  const attention = z.models.filter(needsAttention);
  return (
    <>
      <Section
        title="All models"
        hint="Each model has to beat a plain baseline on data it never saw before anything may use it. Tap a model for its score over time, live shadow and drift."
        right={<span className="text-[13px] text-faint">lab report {z.generated}</span>}
        help="The lab retrains these on a schedule, compares every new version with the one in place, and only keeps a version that is better out of sample."
      >
        {z.headline && <p className="pb-1 text-[15px] leading-relaxed text-ink">{z.headline}</p>}
        {attention.length > 0 && (
          <div className="py-2">
            <Notice tone="warning" title={`${attention.map((m) => m.code).join(", ")} need a look`}>
              Inputs outside the range the model was trained on, a failed retrain or a shadow score that went wrong. Forecasts may be off
              until the next retrain.
            </Notice>
          </div>
        )}
        <List>
          {z.models.map((m) => {
            const e = edgeNow(m);
            const d = m.drift?.level === "drift" || m.drift?.level === "shift" ? driftChip(m.drift.level) : null;
            return (
              <ListRow
                key={m.code}
                leading={<CodeMark code={m.code} />}
                title={m.title}
                subtitle={
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <Badge tone={statusTone(m.status)}>{statusWord(m.status)}</Badge>
                    <span>{retrainWords(m)}</span>
                  </span>
                }
                right={
                  m.higherBetter ? (
                    <span>IC {num(m.modelScore, 3)}</span>
                  ) : (
                    <span className={toneText[tone(e)]}>{e === null ? "n/a" : signedPct(e, 1)}</span>
                  )
                }
                rightSub={d ? <Badge tone={d.tone}>{d.word}</Badge> : <span className="text-muted">vs baseline</span>}
                onClick={() => setOpen(m.code)}
                chevron
              />
            );
          })}
        </List>
      </Section>
      <Sheet open={shown !== null} onClose={() => setOpen(null)} title={shown ? `${shown.code} ${shown.title}` : ""} wide>
        {shown && <ZooDetail m={shown} />}
      </Sheet>
    </>
  );
}

function ZooDetail({ m }: { m: ZooModel }) {
  const pts = edgePoints(m.history, m.higherBetter);
  const won = winShare(m.history, m.higherBetter);
  const e = edgeNow(m);
  const live = m.live;
  const weeks = live ? edgePoints(live.weeks, m.higherBetter) : [];
  const d = driftChip(m.drift?.level);
  const per = m.managedBy === "zoo" ? "period" : "retrain";
  return (
    <div className="space-y-4">
      <p className="text-[15px] leading-relaxed text-ink">
        Forecasts {m.target}, {m.horizon}, for {m.universe}. It has to beat {m.baseline}.
      </p>
      <p className="text-[13px] leading-relaxed text-muted">{m.statusDetail}</p>

      {m.drift?.level === "drift" && (
        <Notice tone="warning" title="Inputs outside the trained range">
          {m.drift.why}. Trees and regressions cannot extrapolate, so forecasts may be off until the next retrain.
        </Notice>
      )}
      {live?.error && (
        <Notice tone="danger" title="Shadow scoring failed">
          {live.error}
        </Notice>
      )}

      <div>
        <h3 className="text-[15px] font-semibold text-ink">Against its baseline over time</h3>
        <p className="mb-3 text-[13px] text-muted">
          {m.managedBy === "zoo"
            ? "Each point is one walk-forward period, forecast by a model that never saw it. Above the dotted line the model was better."
            : "Each point is one retrain, the new version against the one in place."}
        </p>
        <AreaChart
          data={pts.map((p) => p.edge)}
          baseline={0}
          height={140}
          tone={e === null ? "flat" : e > 0 ? "up" : "down"}
          label={`${m.code}: percent better than its baseline per ${per}`}
          renderTip={(i) => `${pts[i]?.label}: ${signedPct(pts[i]?.edge, 1)}`}
          empty="Not enough periods yet."
        />
        {won !== null && (
          <p className="mt-2 text-[13px] text-muted">
            Better in {share(won)} of {plural(pts.length, per)}.
          </p>
        )}
      </div>

      <List>
        <Row
          label="Out of sample"
          sub={METRIC_WORDS[m.metric] ?? m.metric}
          value={fmtScore(m.modelScore, m.metric)}
          valueSub={`baseline ${fmtScore(m.baselineScore, m.metric)}`}
          help={`${m.metric}, ${m.higherBetter ? "higher" : "lower"} is better, on rows the model never trained on.`}
        />
        {!m.higherBetter && <Row label="Better than the baseline" value={e === null ? "n/a" : signedPct(e, 1)} tone={tone(e)} sub="smaller error, out of sample" />}
        <Row
          label="Could it be luck?"
          sub="Diebold-Mariano p; the gate needs below 0.05"
          value={fmtP(m.dmP)}
          help="The chance of a difference this large if model and baseline were equally good. Small means the edge is probably real."
        />
        {m.gate && (
          <Row
            label="Gate"
            sub={m.gate.why}
            value={<Badge tone={m.gate.passed ? "good" : "warn"}>{m.gate.passed ? "passed" : "not passed"}</Badge>}
            help="A model that does not pass is kept and scored in shadow, but nothing may use it."
          />
        )}
        <Row
          label="Live in shadow"
          sub={
            live && live.rows > 0
              ? `${plural(live.rows, "forecast")} scored since ${live.since}, closer than the baseline in ${share(live.winRate)}`
              : live && live.open > 0
                ? `${plural(live.open, "forecast")} written down, waiting for the outcome`
                : m.shadowWhere === "engine"
                  ? "scored live by the engine, above"
                  : "no forecasts yet"
          }
          value={live && live.rows > 0 && !m.higherBetter ? signedPct(live.gainPct, 1) : live && live.rows > 0 ? fmtScore(live.model, m.metric) : "n/a"}
          tone={live && live.rows > 0 && !m.higherBetter ? tone(live.gainPct) : "plain"}
        />
        <Row
          label="Last retrain"
          sub={m.champion ? `in use: ${m.champion.version}${m.champion.trainTo ? `, data to ${m.champion.trainTo}` : ""}` : "no version has passed yet"}
          value={m.managedBy === "retired" ? "retired" : ago(m.lastRetrainMs)}
          valueSub={m.nextDue && m.managedBy !== "retired" ? `next ${m.nextDue}` : undefined}
        />
        <Row label="Inputs" sub={m.drift?.why || "checked against the training data after each run"} value={<Badge tone={d.tone}>{d.word}</Badge>} />
        <Row label="Used by" sub={m.useRule || "not decided"} value={m.usedBy.length ? m.usedBy.join(", ") : "nothing"} />
      </List>

      {weeks.length >= 2 && (
        <div>
          <h3 className="text-[15px] font-semibold text-ink">Live, week by week</h3>
          <p className="mb-2 text-[13px] text-muted">Percent better than the baseline each week since it went into shadow.</p>
          <Sparkline data={weeks.map((w) => w.edge)} height={48} fill label={`${m.code} live edge per week`} />
        </div>
      )}

      <TodayForecasts today={m.extra?.today} />

      {m.drift && m.drift.features.length > 0 && (
        <More title={`All ${plural(m.drift.features.length, "input")}`}>
          <List>
            {m.drift.features.map((f) => {
              const c = driftChip(f.level);
              return (
                <Row
                  key={f.feature}
                  label={<span className="break-all">{f.feature}</span>}
                  sub={`PSI ${num(f.psi)}`}
                  value={<Badge tone={c.tone}>{c.word}</Badge>}
                  valueSub={`${num(f.outsidePct, 1)}% outside`}
                />
              );
            })}
          </List>
        </More>
      )}

      <ExtraNumbers extra={m.extra} />

      {m.decisions.length > 0 && (
        <More title="Champion and challenger">
          <List>
            {m.decisions
              .slice(-6)
              .reverse()
              .map((x, i) => (
                <Row key={i} label={x.date ?? "?"} sub={x.why} value={x.decision} />
              ))}
          </List>
        </More>
      )}
    </div>
  );
}

const fmtValue = (k: string, v: unknown): string => {
  if (typeof v !== "number") return String(v ?? "n/a");
  if (k === "p_up") return share(v);
  if (/^q\d+$/.test(k)) return signedPct(v * 100, 2);
  return num(v, Math.abs(v) >= 10 ? 1 : 3);
};

/** The latest forecasts the model wrote down: one row per coin, or a few named numbers. */
function TodayForecasts({ today }: { today: unknown }) {
  if (Array.isArray(today) && today.length > 0) {
    const rows = today as Record<string, unknown>[];
    const cols = Object.keys(rows[0]).filter((k) => k !== "symbol");
    return (
      <More title="Latest forecasts (shadow, not traded)">
        <List>
          {rows.map((r, i) => (
            <Row key={i} label={String(r.symbol ?? "")} value={cols.map((c) => fmtValue(c, r[c])).join(" · ")} valueSub={cols.join(" · ")} />
          ))}
        </List>
      </More>
    );
  }
  if (today && typeof today === "object") {
    return (
      <More title="Latest forecast (shadow, not traded)">
        <List>
          {Object.entries(today as Record<string, unknown>).map(([k, v]) => (
            <Row key={k} label={k.replace(/_/g, " ")} value={fmtValue(k, v)} />
          ))}
        </List>
      </More>
    );
  }
  return null;
}

/** The secondary numbers a model's card keeps (calibration, coverage, by regime), for the curious. */
function ExtraNumbers({ extra }: { extra: Record<string, unknown> | null | undefined }) {
  const flat: [string, string][] = [];
  const walk = (prefix: string, v: unknown, depth: number) => {
    if (v === null || v === undefined || flat.length >= 40) return;
    if (typeof v === "number" || typeof v === "string" || typeof v === "boolean") {
      flat.push([prefix, typeof v === "number" ? num(v, Math.abs(v) >= 10 ? 1 : 3) : String(v)]);
    } else if (Array.isArray(v)) {
      v.slice(0, 12).forEach((x, i) => {
        const name = x && typeof x === "object" && "quantile" in x ? String((x as { quantile: unknown }).quantile) : x && typeof x === "object" && "symbol" in x ? String((x as { symbol: unknown }).symbol) : String(i + 1);
        if (depth < 2) walk(`${prefix} ${name}`, x, depth + 1);
      });
    } else if (typeof v === "object" && depth < 2) {
      for (const [k, x] of Object.entries(v as Record<string, unknown>)) {
        if (k === "quantile" || k === "symbol") continue;
        walk(prefix ? `${prefix} ${k}` : k, x, depth + 1);
      }
    }
  };
  for (const [k, v] of Object.entries(extra ?? {})) {
    if (k === "today" || k === "calibration" || k === "weights" || k === "top_features") continue;
    walk(k, v, 0);
  }
  if (!flat.length) return null;
  return (
    <More title="More numbers">
      <List>
        {flat.map(([k, v]) => (
          <Row key={k} label={<span className="break-words">{k.replace(/_/g, " ")}</span>} value={v} />
        ))}
      </List>
    </More>
  );
}
