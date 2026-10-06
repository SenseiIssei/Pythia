import { useCallback, useEffect, useState } from "react";
import { Activity, Gauge, RefreshCw, Scale, TriangleAlert, Trophy } from "lucide-react";
import { Badge, Button, Card, PageHeader, StatCard } from "../components/ui";
import { liveMode } from "../live";
import { mlStatus, type DriftLevel, type MlStatus } from "../ml";

const fmtVol = (v: number) => `${v.toFixed(0)} %`;
const NONE = "not yet";
const fmtHour = (ms: number) => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const fmtDate = (ms: number) => new Date(ms).toLocaleDateString();

const DRIFT_TONE: Record<DriftLevel, "green" | "purple" | "red"> = { stable: "green", shift: "purple", drift: "red" };
const DRIFT_WORD: Record<DriftLevel, string> = { stable: "like training", shift: "shifting", drift: "drifted" };

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

  const header = (
    <PageHeader
      title="Models"
      subtitle="Forecasts in shadow mode: written down before the hour, scored after it, never traded"
    />
  );

  if (mode === "none") {
    return (
      <div className="animate-fade-in max-w-5xl">
        {header}
        <Card className="border-warning/30 bg-warning/5">
          <div className="flex items-start gap-3 text-sm text-cyber-text-dim">
            <TriangleAlert size={18} className="mt-0.5 shrink-0 text-warning" />
            Models run in the <span className="text-accent">desktop app</span> or a{" "}
            <span className="text-accent">backend server</span>, not in the browser paper build.
          </div>
        </Card>
      </div>
    );
  }

  const shadow = s?.shadow;
  const gain = shadow?.gainVsHarPct ?? null;
  const notStable = (s?.drift ?? []).filter((d) => d.level !== "stable");

  return (
    <div className="animate-fade-in max-w-5xl space-y-4">
      {header}

      {err && (
        <Card className="border-danger/30 bg-danger/5">
          <div className="text-sm text-danger">{err}</div>
        </Card>
      )}

      {s && s.state !== "live" && (
        <Card className={s.state === "rejected" ? "border-danger/30 bg-danger/5" : "border-warning/30 bg-warning/5"}>
          <div className="flex items-start gap-3 text-sm">
            <TriangleAlert size={18} className={`mt-0.5 shrink-0 ${s.state === "rejected" ? "text-danger" : "text-warning"}`} />
            <div>
              <div className="font-bold text-cyber-text">
                {s.state === "noModel" && "No model loaded"}
                {s.state === "rejected" && "Model refused"}
                {s.state === "warmingUp" && "Warming up"}
              </div>
              <div className="text-cyber-text-dim">{s.message}</div>
            </div>
          </div>
        </Card>
      )}

      {s?.model && (
        <Card
          title="Next-hour volatility"
          right={
            <div className="flex items-center gap-2">
              <Badge tone="purple">shadow mode</Badge>
              <Button tone="neutral" icon={RefreshCw} onClick={() => void refresh()}>
                Refresh
              </Button>
            </div>
          }
        >
          <p className="text-sm text-cyber-text-dim">
            Forecasts how much each coin will move in the coming hour, so position sizes and stops can follow the
            market instead of a fixed guess. Version {s.model.version}, {s.model.trees} trees, trained on data up to{" "}
            {fmtDate(s.model.trainToMs)}. In the lab it was{" "}
            <span className="text-accent">{s.model.labGainVsHarPct.toFixed(1)} %</span> more accurate than the
            standard baseline (HAR), out of sample.
          </p>
        </Card>
      )}

      {shadow && s?.model && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="Hours scored live" value={shadow.scored} icon={Activity} sub={shadow.sinceMs ? `since ${fmtDate(shadow.sinceMs)}` : "first score after the next full hour"} />
          <StatCard
            label="Better than HAR"
            value={gain === null ? NONE : `${gain >= 0 ? "+" : ""}${gain.toFixed(1)} %`}
            icon={Trophy}
            tone={gain === null ? "cyan" : gain > 0 ? "green" : "red"}
            sub="lower forecast error (QLIKE)"
          />
          <StatCard
            label="Hours won"
            value={shadow.winRate === null ? NONE : `${(shadow.winRate * 100).toFixed(0)} %`}
            icon={Scale}
            sub="model closer than HAR"
          />
          <StatCard
            label="Error, model vs HAR"
            value={shadow.qlikeModel === null ? NONE : shadow.qlikeModel.toFixed(3)}
            icon={Gauge}
            sub={shadow.qlikeHar === null ? "" : `HAR ${shadow.qlikeHar.toFixed(3)}`}
          />
        </div>
      )}

      {s && s.coins.length > 0 && (
        <Card title={`Coming hour, from ${fmtHour(s.coins[0].hourMs)}`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-cyber-text-faint">
                  <th className="py-1.5 pr-3">Coin</th>
                  <th className="py-1.5 pr-3 text-right">Model</th>
                  <th className="py-1.5 pr-3 text-right">HAR</th>
                  <th className="py-1.5 pr-3 text-right">Last hour</th>
                  <th className="py-1.5 pr-3 text-right">Week average</th>
                  <th className="py-1.5">Outlook</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {s.coins.map((c) => {
                  const ratio = c.modelVolPct / c.weekVolPct;
                  return (
                    <tr key={c.coin} className="border-t border-cyber-border">
                      <td className="py-1.5 pr-3 font-medium text-cyber-text">{c.coin}</td>
                      <td className="py-1.5 pr-3 text-right text-accent">{fmtVol(c.modelVolPct)}</td>
                      <td className="py-1.5 pr-3 text-right text-cyber-text-dim">{fmtVol(c.harVolPct)}</td>
                      <td className="py-1.5 pr-3 text-right text-cyber-text-dim">{fmtVol(c.lastHourVolPct)}</td>
                      <td className="py-1.5 pr-3 text-right text-cyber-text-dim">{fmtVol(c.weekVolPct)}</td>
                      <td className="py-1.5">
                        {ratio > 1.25 ? (
                          <Badge tone="red">busier than usual</Badge>
                        ) : ratio < 0.8 ? (
                          <Badge tone="green">calmer than usual</Badge>
                        ) : (
                          <Badge tone="neutral">normal</Badge>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-cyber-text-faint">
            Annualised volatility. Model and HAR forecast the coming hour; last hour and week average are what
            happened.
          </p>
        </Card>
      )}

      {s && s.drift.length > 0 && (
        <Card title="Are the inputs still like the training data?">
          {notStable.length === 0 ? (
            <p className="text-sm text-success">
              All {s.drift.length} inputs over the last week look like what the model was trained on.
            </p>
          ) : (
            <p className="mb-3 text-sm text-cyber-text-dim">
              {notStable.length} of {s.drift.length} inputs have moved away from the training data. A drifted model
              answers a question it was not trained for; the weekly retrain picks this up.
            </p>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            {s.drift.map((d) => (
              <span key={d.feature} title={`PSI ${d.psi.toFixed(3)}`}>
                <Badge tone={DRIFT_TONE[d.level]}>
                  {d.feature} · {DRIFT_WORD[d.level]}
                </Badge>
              </span>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
