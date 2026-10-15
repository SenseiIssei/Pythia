import { useCallback, useEffect, useState } from "react";
import { BrainCircuit, RefreshCw } from "lucide-react";
import { Badge, Button, Card, List, Notice, Page, signedPct } from "../design";
import { KeyStats, LoadingRows, More, Nothing, Row, Section, num, pct, plural, share } from "../pagekit";
import { outlook } from "../pagekit/insight";
import { liveMode } from "../live";
import { mlStatus, type MlStatus } from "../ml";
import { DriftRows, PicksPanel } from "../components/PicksPanel";

const fmtVol = (v: number) => pct(v, 0);
const NONE = "not yet";
const fmtHour = (ms: number) => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const fmtDate = (ms: number) => new Date(ms).toLocaleDateString();

export function Models() {
  const mode = liveMode();
  const [s, setS] = useState<MlStatus | null>(null);
  const [err, setErr] = useState("");

  const refresh = useCallback(async () => {
    try {
      setS(await mlStatus());
      setErr("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (mode === "none") return;
    void refresh();
    const t = setInterval(() => void refresh(), 60_000);
    return () => clearInterval(t);
  }, [mode, refresh]);

  const title = "Models";
  const subtitle = "Forecasts in shadow mode: written down before the hour or week, scored after it, never traded.";

  if (mode === "none") {
    return (
      <Page title={title} subtitle={subtitle}>
        <Card>
          <Nothing icon={BrainCircuit} title="Models need the desktop app or a connected server">
            Models run in the desktop app or a backend server, not in the browser paper build.
          </Nothing>
        </Card>
      </Page>
    );
  }

  const shadow = s?.shadow;
  const gain = shadow?.gainVsHarPct ?? null;
  const notStable = (s?.drift ?? []).filter((d) => d.level !== "stable");
  const drifted = (s?.drift ?? []).filter((d) => d.level === "drift");

  return (
    <Page
      title={title}
      subtitle={subtitle}
      right={
        <Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => void refresh()}>
          Refresh
        </Button>
      }
    >
      {shadow && s?.model && (
        <KeyStats
          items={[
            {
              label: "Better than HAR",
              value: gain === null ? NONE : signedPct(gain, 1),
              tone: gain === null ? "plain" : gain > 0 ? "up" : "down",
              sub: "smaller forecast error than the textbook method, live",
            },
            {
              label: "Hours won",
              value: shadow.winRate === null ? NONE : share(shadow.winRate),
              sub: "model closer than HAR",
            },
            {
              label: "Hours scored live",
              value: shadow.scored.toLocaleString(),
              sub: shadow.sinceMs ? `since ${fmtDate(shadow.sinceMs)}` : "first score after the next full hour",
            },
          ]}
        />
      )}

      {err && (
        <Notice tone="danger" title="Could not read the models">
          {err}
        </Notice>
      )}

      {!s && !err && (
        <Card>
          <LoadingRows label="Reading the models" />
        </Card>
      )}

      {s && s.state !== "live" && (
        <Notice
          tone={s.state === "rejected" ? "danger" : "warning"}
          title={s.state === "noModel" ? "No volatility model loaded" : s.state === "rejected" ? "Model refused" : "Warming up"}
        >
          {s.message}
        </Notice>
      )}

      {s?.model && (
        <Section
          title="Next-hour volatility"
          hint="Forecasts how much each coin will move in the coming hour, so position sizes and stops can follow the market instead of a fixed guess."
          right={<Badge tone="accent">shadow mode</Badge>}
        >
          <List>
            <Row
              label="Better than HAR in the lab"
              sub="out of sample, before going live"
              value={signedPct(s.model.labGainVsHarPct, 1)}
              tone={s.model.labGainVsHarPct > 0 ? "up" : "down"}
              help="How much smaller its forecast error was than the standard baseline (HAR) on data it never trained on."
            />
            {shadow && (
              <Row
                label="Error, model vs HAR"
                sub="QLIKE, lower is better"
                value={shadow.qlikeModel === null ? NONE : num(shadow.qlikeModel, 3)}
                valueSub={shadow.qlikeHar === null ? undefined : `HAR ${num(shadow.qlikeHar, 3)}`}
              />
            )}
            <Row label="Version" sub={`${plural(s.model.trees, "tree")}, trained on data up to ${fmtDate(s.model.trainToMs)}`} value={s.model.version} />
          </List>
        </Section>
      )}

      {s && s.coins.length > 0 && (
        <Section
          title={`Coming hour, from ${fmtHour(s.coins[0].hourMs)}`}
          hint="The model's forecast for each coin, against the textbook method and what really happened lately. Annualised volatility."
        >
          <List>
            {s.coins.map((c) => {
              const o = outlook(c.modelVolPct, c.weekVolPct);
              return (
                <Row
                  key={c.coin}
                  label={<span className="font-semibold">{c.coin}</span>}
                  sub={
                    <span className="tabular">
                      HAR {fmtVol(c.harVolPct)} · last hour {fmtVol(c.lastHourVolPct)} · week {fmtVol(c.weekVolPct)}
                    </span>
                  }
                  value={fmtVol(c.modelVolPct)}
                  valueSub={<Badge tone={o.tone}>{o.word}</Badge>}
                />
              );
            })}
          </List>
          <p className="mt-2 text-[13px] text-muted">Model and HAR forecast the coming hour; last hour and week average are what happened.</p>
        </Section>
      )}

      {s && s.drift.length > 0 && (
        <Section title="Are the inputs still like the training data?" hint="Trees cannot extrapolate, so inputs outside what the model has seen make forecasts less reliable.">
          {drifted.length > 0 ? (
            <Notice tone="warning">
              {drifted.length} of {s.drift.length} inputs spent more than 5% of the last week outside the range the model was
              trained on. Trees cannot extrapolate, so forecasts may be off until the weekly retrain has seen this market.
            </Notice>
          ) : notStable.length === 0 ? (
            <Notice tone="success">All {s.drift.length} market inputs over the last week sit inside what the model was trained on.</Notice>
          ) : (
            <p className="text-[15px] leading-relaxed text-ink">
              All inputs are inside the trained range. {notStable.length} of {s.drift.length} are spread differently from the
              six-year average, which is normal: a single week is one market regime.
            </p>
          )}
          <div className="mt-2">
            <More title={`All ${plural(s.drift.length, "input")}`}>
              <DriftRows drift={s.drift} />
            </More>
          </div>
        </Section>
      )}

      {s?.picks && <PicksPanel p={s.picks} onChanged={() => void refresh()} />}
    </Page>
  );
}
