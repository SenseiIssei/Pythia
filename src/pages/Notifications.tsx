import { useCallback, useEffect, useState } from "react";
import { Bell, BellOff, FileText, Send } from "lucide-react";
import { Button, Card, Chip, Empty, ListRow, Page, SectionTitle, Sheet, Skeleton, type ChipTone } from "../design";
import { shortLine, timeOfDay, dayLabel } from "../flows/activity";
import {
  MUTE_CHOICES,
  alertTitle,
  alertsAvailable,
  countsLine,
  deliveryOf,
  destinationName,
  fetchAlerts,
  muteText,
  sendTest,
  setMute,
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
            {view.lastDigest && <p className="whitespace-pre-line break-words text-sm">{view.lastDigest.text}</p>}
          </Card>

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
                        icon={Bell}
                        title={alertTitle(a)}
                        subtitle={shortLine(a.text.replace(/\*\*/g, ""), 140)}
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
