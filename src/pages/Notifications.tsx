import { useCallback, useEffect, useState } from "react";
import { Bell, BellOff, FileText, Image as ImageIcon, Moon, Send } from "lucide-react";
import { Button, Card, Chip, Empty, ListRow, Page, SectionTitle, Segmented, Sheet, Skeleton, type ChipTone } from "../design";
import { shortLine, timeOfDay, dayLabel } from "../flows/activity";
import {
  ALERT_LANGUAGES,
  MUTE_CHOICES,
  alertTitle,
  alertsAvailable,
  countsLine,
  deliveryOf,
  destinationName,
  fetchAlerts,
  fetchSettings,
  groupCategories,
  languageOf,
  muteText,
  plainText,
  quietLine,
  saveSettings,
  sendTest,
  setMute,
  validHhmm,
  type AlertCategoryView,
  type AlertLanguage,
  type AlertSettingsPatch,
  type AlertSettingsView,
  type AlertsView,
  type DeliveryTone,
} from "../flows/alerts";

const TONE: Record<DeliveryTone, ChipTone> = { good: "good", warn: "warn", bad: "bad", neutral: "neutral" };

const REFRESH_MS = 30_000;

/**
 * The alerts Pythia sent (or held back), with mute and test buttons and the
 * last daily report. Reads GET /api/alerts from the Pythia server.
 */
export function Notifications() {
  const [view, setView] = useState<AlertsView | null>(null);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [muting, setMuting] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const available = alertsAvailable();

  const read = useCallback(async () => {
    const r = await fetchAlerts();
    setNow(Date.now());
    if (r.ok) {
      setView(r.data);
      setErr("");
    } else setErr(r.error);
  }, []);

  useEffect(() => {
    if (!available) return;
    void read();
    const t = setInterval(() => void read(), REFRESH_MS);
    return () => clearInterval(t);
  }, [available, read]);

  async function test() {
    setBusy(true);
    setNote("");
    const r = await sendTest();
    setNote(r.ok ? "Test message sent." : r.error);
    setBusy(false);
    void read();
  }

  async function mute(minutes: number) {
    setBusy(true);
    setNote("");
    const r = await setMute(minutes);
    if (!r.ok) setNote(r.error);
    setBusy(false);
    setMuting(false);
    void read();
  }

  if (!available) {
    return (
      <Page title="Notifications">
        <Card>
          <Empty icon={Bell} title="Not connected">
            Alerts are sent by the Pythia server. Connect this app to it to see them here.
          </Empty>
        </Card>
      </Page>
    );
  }

  const muted = view ? muteText(view.mutedUntilMs, now) : null;

  return (
    <Page title="Notifications">
      {!view && !err ? (
        <Card>
          <Skeleton className="h-5 w-40" />
          <Skeleton className="mt-3 h-4 w-56" />
        </Card>
      ) : err && !view ? (
        <Card>
          <Empty icon={BellOff} title="Could not load alerts" action={<Button variant="secondary" onClick={() => void read()}>Try again</Button>}>
            {err}
          </Empty>
        </Card>
      ) : view ? (
        <>
          <Card>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[17px] font-semibold tracking-tight">
                  {!view.enabled ? "Alerts are off" : muted ?? `Sending to ${destinationName(view.destination)}`}
                </p>
                <p className="text-muted text-sm">
                  {!view.enabled ? "Set an alert destination on the server to turn them on." : countsLine(view.counts)}
                </p>
              </div>
              <Chip tone={!view.enabled ? "neutral" : muted ? "warn" : "good"}>{!view.enabled ? "Off" : muted ? "Muted" : "On"}</Chip>
            </div>
            {view.enabled && (
              <div className="mt-4 grid grid-cols-2 gap-2">
                {muted ? (
                  <Button variant="secondary" icon={Bell} disabled={busy} onClick={() => void mute(0)}>
                    Unmute
                  </Button>
                ) : (
                  <Button variant="secondary" icon={BellOff} disabled={busy} onClick={() => setMuting(true)}>
                    Mute
                  </Button>
                )}
                <Button variant="secondary" icon={Send} disabled={busy} onClick={() => void test()}>
                  Send test
                </Button>
              </div>
            )}
            {note && (
              <p role="status" className="text-muted mt-2 text-sm">
                {note}
              </p>
            )}
          </Card>

          <Card>
            <ListRow
              icon={FileText}
              title="Last daily report"
              subtitle={view.lastDigest ? `${dayLabel(view.lastDigest.ts, now)}, ${timeOfDay(view.lastDigest.ts)}` : "None yet"}
            />
            {view.lastDigest && <p className="whitespace-pre-line break-words text-sm">{plainText(view.lastDigest.text)}</p>}
          </Card>

          <AlertSettings />

          <SectionTitle>Recent</SectionTitle>
          <Card className="py-1">
            {view.recent.length === 0 ? (
              <Empty icon={Bell} title="No alerts yet">
                Starts, stops, loss limits and problems show up here.
              </Empty>
            ) : (
              <ul className="divide-y">
                {view.recent.map((a, i) => {
                  const d = deliveryOf(a);
                  return (
                    <li key={`${a.ts}:${i}`}>
                      <ListRow
                        icon={a.photo ? ImageIcon : Bell}
                        title={alertTitle(a)}
                        subtitle={shortLine(plainText(a.text), 140)}
                        right={<span className="text-muted text-sm font-normal">{`${dayLabel(a.ts, now)} ${timeOfDay(a.ts)}`}</span>}
                        rightSub={<Chip tone={TONE[d.tone]} title={d.label}>{d.label.startsWith("Failed") ? "Failed" : d.label}</Chip>}
                      />
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </>
      ) : null}

      <Sheet open={muting} title="Mute alerts" onClose={() => setMuting(false)}>
        <p className="text-muted text-[15px]">Nothing is sent while muted. Alerts are still listed here.</p>
        <div className="mt-4 space-y-2">
          {MUTE_CHOICES.map((c) => (
            <Button key={c.minutes} variant="secondary" full disabled={busy} onClick={() => void mute(c.minutes)}>
              {`For ${c.label}`}
            </Button>
          ))}
        </div>
      </Sheet>
    </Page>
  );
}

/** A switch: on or off, nothing else. */
function Switch({ on, label, disabled, onChange }: { on: boolean; label: string; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className="fl-focus relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors disabled:opacity-40"
      style={{ background: on ? "var(--fl-up)" : "var(--fl-surface-2)", border: "1px solid var(--fl-line)" }}
    >
      <span
        aria-hidden
        className="inline-block h-5 w-5 rounded-full shadow transition-transform"
        style={{ background: "var(--fl-surface)", transform: on ? "translateX(22px)" : "translateX(3px)" }}
      />
    </button>
  );
}

function CategoryRow({ c, busy, onToggle }: { c: AlertCategoryView; busy: boolean; onToggle: (on: boolean) => void }) {
  return (
    <li className="flex items-center gap-3 py-3">
      <span className="fl-surface-2 flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-lg" aria-hidden>
        {c.emoji}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[15px] font-semibold">{c.label}</span>
        <span className="fl-muted block break-words text-sm">{c.about}</span>
      </span>
      <Switch on={c.on} label={c.label} disabled={busy} onChange={onToggle} />
    </li>
  );
}

/** The language of the messages to the chat; the app itself stays in English. */
function LanguageCard({ s, busy, onPick }: { s: AlertSettingsView; busy: boolean; onPick: (l: AlertLanguage) => void }) {
  const { lang, note } = languageOf(s);
  return (
    <Card label="Message language">
      <p className="text-[15px] font-semibold">Message language</p>
      <p className="fl-muted text-sm">The language of the messages to the chat: cards, digests and charts. The app stays in English.</p>
      <div className="mt-3" aria-disabled={busy || note != null}>
        <Segmented
          label="Message language"
          options={ALERT_LANGUAGES}
          value={lang}
          onChange={(l) => {
            if (!busy && note == null && l !== lang) onPick(l);
          }}
        />
      </div>
      {note && <p className="fl-muted mt-2 text-sm">{note}</p>}
    </Card>
  );
}

/**
 * What is sent and when: one switch per category, quiet hours and the size of
 * a big move. Saved on the server with the engine state; the lab's digests
 * follow the same switches.
 */
function AlertSettings() {
  const [s, setS] = useState<AlertSettingsView | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [quiet, setQuiet] = useState({ start: "", end: "" });
  const [moves, setMoves] = useState({ hour: "", day: "" });

  const take = useCallback((v: AlertSettingsView) => {
    setS(v);
    setQuiet({ start: v.quietHours.start, end: v.quietHours.end });
    setMoves({ hour: String(v.bigMoves.hourPct), day: String(v.bigMoves.dayPct) });
  }, []);

  useEffect(() => {
    void fetchSettings().then((r) => (r.ok ? take(r.data) : setErr(r.error)));
  }, [take]);

  async function save(patch: AlertSettingsPatch) {
    setBusy(true);
    setErr("");
    const r = await saveSettings(patch);
    if (r.ok) take(r.data);
    else setErr(r.error);
    setBusy(false);
  }

  if (!s) {
    return err ? (
      <Card>
        <p className="fl-muted text-sm">{`Settings could not be read: ${err}`}</p>
      </Card>
    ) : null;
  }

  const groups = groupCategories(s.categories);
  const quietChanged = quiet.start !== s.quietHours.start || quiet.end !== s.quietHours.end;
  const quietOk = validHhmm(quiet.start) && validHhmm(quiet.end);
  const hour = Number(moves.hour);
  const day = Number(moves.day);
  const movesChanged = hour !== s.bigMoves.hourPct || day !== s.bigMoves.dayPct;
  const movesOk = hour >= 0.5 && hour <= 50 && day >= 1 && day <= 90;

  return (
    <>
      <div className="px-1 pt-2">
        <h2 className="text-lg font-semibold tracking-tight">What is sent</h2>
        <p className="fl-muted text-sm">The kill switch, a loss floor and the daily loss brake always go out.</p>
      </div>
      {[
        { title: "From the engine", items: groups.engine },
        { title: "From the lab", items: groups.lab },
      ].map((g) => (
        <Card key={g.title} className="py-1" label={g.title}>
          <p className="fl-muted pt-3 text-xs font-semibold uppercase tracking-wide">{g.title}</p>
          <ul className="divide-y" style={{ borderColor: "var(--fl-line)" }}>
            {g.items.map((c) => (
              <CategoryRow key={c.id} c={c} busy={busy} onToggle={(on) => void save({ categories: { [c.id]: on } })} />
            ))}
          </ul>
        </Card>
      ))}

      <Card label="Quiet hours">
        <div className="flex items-start gap-3">
          <span className="fl-surface-2 flex h-10 w-10 shrink-0 items-center justify-center rounded-full" aria-hidden>
            <Moon size={18} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[15px] font-semibold">Quiet hours</span>
            <span className="fl-muted block text-sm">
              {s.quietHours.enabled
                ? `${quietLine(s.quietHours)} ${s.quietHours.timezone}${s.quietNow ? ", quiet now" : ""}. Only urgent alerts; the rest are listed in one message after.`
                : "Off: everything goes out at once."}
            </span>
          </span>
          <Switch on={s.quietHours.enabled} label="Quiet hours" disabled={busy} onChange={(on) => void save({ quietHours: { enabled: on } })} />
        </div>
        {s.quietHours.enabled && (
          <div className="mt-3 grid grid-cols-2 gap-2">
            <label className="text-sm">
              <span className="fl-muted">From</span>
              <input type="time" className="fl-input fl-num mt-1" value={quiet.start} onChange={(e) => setQuiet({ ...quiet, start: e.target.value })} />
            </label>
            <label className="text-sm">
              <span className="fl-muted">To</span>
              <input type="time" className="fl-input fl-num mt-1" value={quiet.end} onChange={(e) => setQuiet({ ...quiet, end: e.target.value })} />
            </label>
            {quietChanged && (
              <div className="col-span-2">
                <Button full disabled={busy || !quietOk} onClick={() => void save({ quietHours: { start: quiet.start, end: quiet.end } })}>
                  Save quiet hours
                </Button>
              </div>
            )}
          </div>
        )}
      </Card>

      <LanguageCard s={s} busy={busy} onPick={(language) => void save({ language })} />

      <Card label="Big moves">
        <p className="text-[15px] font-semibold">Big moves</p>
        <p className="fl-muted text-sm">A held coin or an autopilot's equity moving more than this. Twice as much on an autopilot counts as urgent.</p>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <label className="text-sm">
            <span className="fl-muted">In an hour, %</span>
            <input inputMode="decimal" className="fl-input fl-num mt-1" value={moves.hour} onChange={(e) => setMoves({ ...moves, hour: e.target.value })} />
          </label>
          <label className="text-sm">
            <span className="fl-muted">In a day, %</span>
            <input inputMode="decimal" className="fl-input fl-num mt-1" value={moves.day} onChange={(e) => setMoves({ ...moves, day: e.target.value })} />
          </label>
          {movesChanged && (
            <div className="col-span-2">
              <Button full disabled={busy || !movesOk} onClick={() => void save({ bigMoves: { hourPct: hour, dayPct: day } })}>
                Save big moves
              </Button>
            </div>
          )}
        </div>
      </Card>
      {err && (
        <p role="status" className="fl-down px-1 text-sm">
          {err}
        </p>
      )}
    </>
  );
}
