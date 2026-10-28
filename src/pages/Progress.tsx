// Fortschritt: how far Pythia is from real money, one column for the owner's
// phone (?page=progress&embed=1, also in the DevPanel). The readiness ladder
// (each candidate's step and what is missing next), P3's 10 EUR pump.fun
// books, paper minus live, the tsmom books' gate 7 and the newest weekly page.
// Every card names its report and how old it is; a card whose report is older
// than its schedule allows says "veraltet" in red and dims its numbers. Read every 2 minutes
// while shown. Read only: nothing here trades or changes a setting.

import { useRef, useState, type ReactNode } from "react";
import { Milestone, RefreshCw } from "lucide-react";
import { Card, Chip, Notice, Page } from "../design";
import { LoadingRows } from "../pagekit";
import { useVisiblePoll } from "../pageVisible";
import {
  PROGRESS_POLL_MS,
  ageText,
  canReadProgress,
  daysToGo,
  de,
  fetchProgress,
  freshness,
  missingGate,
  pctText,
  share,
  type Gap,
  type Gate7,
  type Ladder,
  type Progress as Data,
  type Source,
  type Ten,
  type Weekly,
} from "../progress";

/** How many candidates the ladder shows before "alle zeigen". */
const LADDER_ROWS = 8;

/** The age line under a card's title: the report, how old, and "veraltet" when it is. */
export function Age({ s, nowMs }: { s: Source; nowMs: number }) {
  const f = freshness(s, nowMs);
  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-muted" data-age={f}>
      {f === "stale" && <Chip tone="bad">veraltet</Chip>}
      {f === "unknown" && <Chip tone="warn">Zeit unbekannt</Chip>}
      <span className={`tabular ${f === "stale" ? "font-semibold text-down" : ""}`}>
        {f === "missing" ? "fehlt" : `Stand ${ageText(s.atMs, nowMs)}`}
      </span>
      <span className="break-all">{s.file}</span>
    </div>
  );
}

/** A card whose numbers dim when its report is stale. */
function Section({ title, s, nowMs, children }: { title: string; s: Source; nowMs: number; children: ReactNode }) {
  const f = freshness(s, nowMs);
  return (
    <Card title={title}>
      <Age s={s} nowMs={nowMs} />
      {f === "missing" ? (
        <p className="text-[14px] text-muted">Der Bericht fehlt.</p>
      ) : (
        <div className={f === "stale" ? "opacity-60" : ""}>{children}</div>
      )}
    </Card>
  );
}

function Bar({ value, ok }: { value: number; ok: boolean }) {
  return (
    <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-surface-2" aria-hidden>
      <div className={`h-full rounded-full ${ok ? "bg-up" : "bg-accent"}`} style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  );
}

function Row({ label, value, tone }: { label: ReactNode; value: ReactNode; tone?: "good" | "bad" }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 text-[14px]">
      <span className="min-w-0 text-muted">{label}</span>
      <span className={`tabular shrink-0 font-semibold ${tone === "good" ? "text-up" : tone === "bad" ? "text-down" : "text-ink"}`}>{value}</span>
    </div>
  );
}

export function LadderCard({ l, nowMs }: { l: Ladder; nowMs: number }) {
  const [all, setAll] = useState(false);
  const rows = all ? l.rows : l.rows.slice(0, LADDER_ROWS);
  return (
    <Section title="Leiter zum Echtgeld" s={l} nowMs={nowMs}>
      <p className="text-[15px] text-ink" data-top="">
        Höchste Stufe: <b>{l.topStep ?? "k. A."}</b> {l.topName ? `(${l.topName})` : ""} von 6, {l.rows.length} Kandidaten
      </p>
      {l.counts.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {l.counts.map((c) => (
            <Chip key={c.step} tone={c.n > 0 && c.step >= 3 ? "good" : "neutral"}>
              {c.step} {c.name}: {c.n}
            </Chip>
          ))}
        </div>
      )}
      <ol className="mt-3 divide-y divide-line">
        {rows.map((r) => (
          <li key={r.id || r.name} className="py-2" data-row={r.name}>
            <div className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 break-words text-[14px] font-semibold text-ink">{r.name}</span>
              <span className="tabular shrink-0 text-[13px] text-muted">
                Stufe {r.step} {r.stepName}
              </span>
            </div>
            {r.next && <p className="mt-0.5 break-words text-[13px] leading-snug text-muted">Als Nächstes fehlt: {r.next}</p>}
            {r.tainted > 0 && <p className="text-[12px] text-warn">{r.tainted} belastete Zahlen</p>}
          </li>
        ))}
      </ol>
      {l.rows.length > LADDER_ROWS && (
        <button type="button" onClick={() => setAll(!all)} className="mt-2 text-[13px] font-semibold text-accent">
          {all ? "Weniger zeigen" : `Alle ${l.rows.length} zeigen`}
        </button>
      )}
      {l.nTrials != null && (
        <p className="mt-3 text-[12px] text-muted">
          Register: {de(l.nTrials, 0)} Versuche, Rauschbalken {de(l.sr0, 2)} Sharpe im Jahr
        </p>
      )}
    </Section>
  );
}

export function TenCard({ t, nowMs }: { t: Ten; nowMs: number }) {
  return (
    <Section title="pump.fun mit 10 EUR (P3)" s={t} nowMs={nowMs}>
      {!t.started ? (
        <p className="text-[15px] font-semibold text-ink" data-ten="not-started">
          Nicht gestartet
        </p>
      ) : (
        <div className="space-y-4">
          {t.books.map((b) => {
            const miss = missingGate(b);
            return (
              <div key={b.book} data-book={b.book}>
                <div className="flex items-baseline justify-between gap-3">
                  <span className="min-w-0 break-all text-[14px] font-semibold text-ink">{b.book}</span>
                  <Chip tone={b.pass ? "good" : "neutral"}>{b.pass ? "Tor offen" : b.started ? "läuft" : "nicht gestartet"}</Chip>
                </div>
                <Row label="Wallet" value={`${de(b.sol, 4)} SOL${b.eur != null ? ` = ${de(b.eur, 2)} EUR` : ""}`} />
                <Row label="Trades" value={de(b.trades, 0)} />
                <Row label="Mittel je Trade" value={pctText(b.mean)} tone={b.mean == null ? undefined : b.mean > 0 ? "good" : "bad"} />
                <Row label="95-%-Band" value={b.band ? `${pctText(b.band[0])} bis ${pctText(b.band[1])}` : "k. A."} />
                <Row label="Tage" value={`${de(b.days, 1)} von ${b.needDays}`} />
                <Bar value={share(b.days, b.needDays)} ok={b.pass} />
                {!b.canPay && <p className="mt-1 text-[12px] text-down">kann keinen Trade mehr bezahlen</p>}
                <p className="mt-1 text-[13px] text-muted">{miss.length ? `Es fehlt: ${miss.join(", ")}` : "Alle Bedingungen erfüllt, der Besitzer entscheidet."}</p>
              </div>
            );
          })}
        </div>
      )}
    </Section>
  );
}

export function GapCard({ g, nowMs }: { g: Gap; nowMs: number }) {
  const c = g.calibration;
  return (
    <Section title="Papier minus live" s={g} nowMs={nowMs}>
      {c ? (
        <>
          <p className="text-[13px] text-muted">
            Kalibrierung {c.rule}: {c.pairs} Paare aus {c.live} live und {c.paper} Papier{c.days != null ? ` in ${de(c.days, 1)} Tagen` : ""}
          </p>
          <Row label="Median je Trade" value={`${de(c.medianPts, 1, true)} Punkte`} />
          <Row label="Mittel je Trade" value={`${de(c.meanPts, 1, true)} Punkte`} />
          {c.verdict && <Row label="Urteil" value={c.verdict} />}
        </>
      ) : (
        <p className="text-[14px] text-muted">Kalibrierung: keine Zahlen.</p>
      )}
      {g.p2 && g.p2.pts != null ? (
        <Row
          label={`P2-Lücke (Tor unter ${de(g.p2.gatePts, 0)})`}
          value={`${de(g.p2.pts, 1, true)} Punkte, ${g.p2.pass ? "besteht" : "nicht"}`}
          tone={g.p2.pass ? "good" : "bad"}
        />
      ) : (
        <Row label="P2-Lücke" value="nicht gemessen" />
      )}
    </Section>
  );
}

export function Gate7Card({ g, nowMs }: { g: Gate7; nowMs: number }) {
  return (
    <Section title="tsmom-Bücher: Tor 7" s={g} nowMs={nowMs}>
      {g.books.length === 0 && <p className="text-[14px] text-muted">Keine Bücher im Bericht.</p>}
      <div className="space-y-3">
        {g.books.map((b) => (
          <div key={b.book} data-gate7={b.book}>
            <div className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 break-all text-[14px] font-semibold text-ink">{b.book}</span>
              <Chip tone={b.ready ? "good" : "neutral"}>{b.ready ? "bereit zum Urteil" : `noch ${daysToGo(b.days, b.needDays)} Tage`}</Chip>
            </div>
            <Row label="Tage" value={`${b.days} von ${b.needDays}`} />
            <Bar value={share(b.days, b.needDays)} ok={b.ready} />
            <Row label="Umschichtungen" value={`${b.rebalances} von ${b.needRebalances}`} />
            <Row label="Papier gegen Backtest" value={`${de(b.paperPct, 1, true)} % gegen ${de(b.backtestPct, 1, true)} %`} />
          </div>
        ))}
      </div>
    </Section>
  );
}

export function WeeklyCard({ w, nowMs }: { w: Weekly; nowMs: number }) {
  if (!w.found) {
    return (
      <Card title="Wochenseite">
        <Age s={w} nowMs={nowMs} />
        <p className="text-[14px] text-muted">Noch keine Wochenseite (sonntags 18:00 UTC).</p>
      </Card>
    );
  }
  return (
    <Section title="Wochenseite" s={w} nowMs={nowMs}>
      <div className="space-y-1 text-[13px] leading-snug text-ink">
        {w.lines.map((ln, i) => (
          <p key={i} className={`break-words ${ln.startsWith("#") ? "font-semibold" : ""}`}>
            {ln.replace(/^#+\s*/, "")}
          </p>
        ))}
      </div>
    </Section>
  );
}

/** The whole page from the data, at `nowMs`; also what the tests render. */
export function ProgressBody({ d, nowMs }: { d: Data; nowMs: number }) {
  if (!d.found) {
    return (
      <Notice tone="info" title="Noch keine Daten" icon={Milestone}>
        Der Lab-Job „progress“ hat noch nichts geschrieben.
      </Notice>
    );
  }
  return (
    <div className="space-y-4">
      {d.updatedMs != null && nowMs - d.updatedMs > 3_600_000 && (
        <Notice tone="warning" title="Die Seite selbst ist alt">
          Zuletzt gebaut {ageText(d.updatedMs, nowMs)}: der Job „progress“ läuft nicht.
        </Notice>
      )}
      <LadderCard l={d.ladder} nowMs={nowMs} />
      <TenCard t={d.ten} nowMs={nowMs} />
      <GapCard g={d.gap} nowMs={nowMs} />
      <Gate7Card g={d.gate7} nowMs={nowMs} />
      <WeeklyCard w={d.weekly} nowMs={nowMs} />
    </div>
  );
}

export function Progress() {
  const ref = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<Data | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const read = () =>
    canReadProgress()
      ? fetchProgress()
          .then((d) => {
            setData(d);
            setErr(null);
          })
          .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      : undefined;
  const [, refresh] = useVisiblePoll(ref, read, PROGRESS_POLL_MS);
  const nowMs = Date.now();
  return (
    <div ref={ref}>
      <Page
        title="Fortschritt"
        subtitle="Wie weit Pythia vom echten Geld entfernt ist. Jede Zahl mit ihrem Alter."
        right={
          <button type="button" onClick={() => void refresh()} aria-label="Neu laden" className="rounded-full p-1.5 text-muted hover:bg-surface-2 hover:text-ink">
            <RefreshCw size={15} aria-hidden />
          </button>
        }
      >
        {!canReadProgress() ? (
          <Notice tone="info" title="Braucht den Server" icon={Milestone}>
            Die Zahlen kommen vom verbundenen Server des Labors.
          </Notice>
        ) : err && !data ? (
          <Notice tone="warning" title="Der Fortschritt konnte nicht gelesen werden">
            {err}
          </Notice>
        ) : !data ? (
          <LoadingRows rows={6} label="Der Fortschritt wird geladen" />
        ) : (
          <>
            {err && (
              <Notice tone="warning" title="Neu laden fehlgeschlagen">
                {err} Die Zahlen unten sind vom letzten Laden; ihr Alter steht an jeder Karte.
              </Notice>
            )}
            <ProgressBody d={data} nowMs={nowMs} />
          </>
        )}
      </Page>
    </div>
  );
}
