import { useState } from "react";
import { Play, Pause, Radio, FlaskConical, AlertTriangle } from "lucide-react";
import { useStore } from "../store";
import { Button, Card, PageHeader, Badge, Sparkline, fmtUsd } from "../components/ui";
import type { StrategyConfig } from "../types";

export function Strategies() {
  const { strategies } = useStore();
  return (
    <div className="animate-fade-in">
      <PageHeader title="Strategies" subtitle="Prove in paper · arm live deliberately" />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {strategies.map((s) => (
          <StrategyCard key={s.id} s={s} />
        ))}
      </div>
    </div>
  );
}

function StrategyCard({ s }: { s: StrategyConfig }) {
  const { setStrategyState, setStrategyParam } = useStore();
  const [confirm, setConfirm] = useState(false);
  const [typed, setTyped] = useState("");

  const live = s.state === "live";
  const paused = s.state === "paused";

  function armLive() {
    if (typed.trim() === s.name) {
      setStrategyState(s.id, "live");
      setConfirm(false);
      setTyped("");
    }
  }

  return (
    <Card>
      <div className="mb-3 flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold">{s.name}</span>
            <Badge tone={live ? "red" : paused ? "neutral" : "cyan"}>
              {live ? "LIVE" : paused ? "PAUSED" : "PAPER"}
            </Badge>
          </div>
          <div className="mt-0.5 text-xs text-cyber-text-faint">
            {s.kind} · {s.universe.length} markets · budget {s.budgetPct}%
          </div>
        </div>
        <div className={`text-right text-lg font-bold ${s.pnl >= 0 ? "text-success" : "text-danger"}`}>
          {fmtUsd(s.pnl)}
          <div className="text-xs font-normal text-cyber-text-faint">
            {s.trades} trades · {(s.winRate * 100).toFixed(0)}% win
          </div>
        </div>
      </div>

      <Sparkline data={s.equityCurve.length > 1 ? s.equityCurve : [0, 0]} height={44} tone={s.pnl >= 0 ? "green" : "red"} />

      {/* params */}
      <div className="mt-3 space-y-2">
        {s.params.map((p) => (
          <div key={p.key} className="flex items-center gap-3 text-xs">
            <span className="w-28 text-cyber-text-dim">{p.label}</span>
            <input
              type="range"
              min={p.min}
              max={p.max}
              step={p.step}
              value={p.value}
              onChange={(e) => setStrategyParam(s.id, p.key, Number(e.target.value))}
              className="flex-1 accent-[#00f0ff]"
            />
            <span className="w-12 text-right font-mono text-accent">{p.value}</span>
          </div>
        ))}
      </div>

      {/* controls */}
      <div className="mt-4 flex items-center justify-between border-t border-cyber-border pt-3">
        <div className="flex items-center gap-2">
          {paused ? (
            <Button tone="cyan" icon={Play} onClick={() => setStrategyState(s.id, "paper")}>
              Resume (paper)
            </Button>
          ) : (
            <Button tone="neutral" icon={Pause} onClick={() => setStrategyState(s.id, "paused")}>
              Pause
            </Button>
          )}
          {!paused && (
            <Button icon={FlaskConical} tone="cyan" onClick={() => setStrategyState(s.id, "paper")} disabled={s.state === "paper"}>
              Paper
            </Button>
          )}
        </div>

        <div className="flex items-center gap-2">
          {live ? (
            <Button tone="red" icon={Radio} onClick={() => setStrategyState(s.id, "paper")}>
              Disarm live
            </Button>
          ) : (
            <Button tone="red" icon={Radio} onClick={() => setConfirm((c) => !c)} disabled={paused}>
              Arm live…
            </Button>
          )}
        </div>
      </div>

      {/* arm-live confirmation */}
      {confirm && !live && (
        <div className="mt-3 rounded-lg border border-danger/40 bg-danger/5 p-3">
          <div className="mb-2 flex items-center gap-2 text-xs text-danger">
            <AlertTriangle size={14} />
            Arming live routes REAL orders using this venue's API keys. Type the strategy name to confirm.
          </div>
          <div className="flex gap-2">
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={s.name}
              className="flex-1 rounded border border-cyber-border bg-cyber-surface px-2 py-1 text-sm focus:border-danger focus:outline-none"
            />
            <Button tone="red" onClick={armLive} disabled={typed.trim() !== s.name}>
              Confirm live
            </Button>
          </div>
          <div className="mt-2 text-[11px] text-cyber-text-faint">
            (In this paper build, "live" only flips the badge — no keys are configured, so no real
            orders can leave. See Settings & SAFETY.md.)
          </div>
        </div>
      )}
    </Card>
  );
}
